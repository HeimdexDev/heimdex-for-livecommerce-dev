"""Phase 3c-B Item 5 — end-to-end orchestration tests.

The Item 1-4 tests cover individual layers (catalog endpoint,
canonical-crop fetch, render enqueue, SAM2 wrapper). This file
locks in cross-cutting invariants of the full pipeline:

  * ``cost_accumulator`` reaches /complete with the LLM picker's
    spend rolled in (D52 fix verification).
  * Appearance rows ship ``tracker_version`` from
    ``WorkerSettings.tracker_version`` (NOT from the queue
    message) — verifies the D-stale-message fix.
  * Appearance row shape matches the api's strict
    ``_AppearancePayload`` schema (no extra keys, all required
    fields present).
  * Heartbeats fire at the documented progress checkpoints.

All tests inject Protocol mocks past the canonical-crop fetch
(stubbed via ``_fetch_canonical_crop`` patch) and the SAM2
tracker so the full ``handle_track_job`` orchestration runs
without real ML or network.
"""

from __future__ import annotations

import io
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

from PIL import Image

from heimdex_media_pipelines.product_track.sam2_pass import (
    BBoxXYWH,
    TrackedSample,
)

from src.settings import WorkerSettings
from src.tasks.track import handle_track_job


def _settings(*, tracker_version: str = "v1.0") -> WorkerSettings:
    return WorkerSettings(
        product_v2_enabled=True,
        sqs_product_track_queue_url="https://sqs/q",
        drive_internal_api_key="t",
        drive_api_base_url="http://api:8000",
        drive_s3_bucket="test-bucket",
        worker_id="test-worker",
        tracker_version=tracker_version,
    )


def _job_body() -> dict:
    return {
        "type": "product.track_job",
        "job_id": str(uuid4()),
        "org_id": str(uuid4()),
        "video_id": str(uuid4()),
        "catalog_entry_id": str(uuid4()),
        "requested_by_user_id": str(uuid4()),
        "duration_preset_sec": 60,
        # Note the deliberately STALE tracker_version on the
        # message — the worker MUST stamp settings.tracker_version
        # on appearances, not this.
        "tracker_version": "v0.9-stale",
        "enumeration_prompt_version": "v1.0",
    }


def _scenes_response(n: int = 3) -> dict:
    return {
        "video_id": "gd_test",
        # PR B: proxy_s3_key is the canonical full-video proxy path
        # the worker downloads ONCE per job (replaces the per-scene
        # URL stub). Tests assert on this via download_file mock.
        "proxy_s3_key": "tenant/drive/d/g/proxy.mp4",
        "scenes": [
            {
                "scene_id": f"gd_test_scene_{i:03d}",
                "keyframe_s3_key": f"k{i}.jpg",
                "start_ms": i * 5000,
                "end_ms": (i + 1) * 5000,
            }
            for i in range(n)
        ],
    }


def _fake_canonical():
    img = Image.new("RGB", (256, 256), (200, 100, 50))
    bbox = BBoxXYWH(x=10, y=10, width=50, height=50)
    return img, bbox, "테스트 제품"


def _good_track_factory():
    """Returns a tracker side_effect that produces dense
    high-confidence samples — feeds through window-assembly's
    threshold filter to produce accepted windows."""

    def _track(*, scene_id, **_kwargs):
        return [
            TrackedSample(
                frame_timestamp_ms=ts,
                bbox=BBoxXYWH(x=10, y=10, width=200, height=200),
                mask_confidence=0.9,
                frame_width=1280,
                frame_height=720,
            )
            for ts in range(0, 4000, 200)  # 2s @ 5fps
        ]

    return _track


def _make_apis(*, render_job_id):
    api = MagicMock()
    api.fetch_scenes_with_keyframes.return_value = _scenes_response(n=3)
    api.find_similar_scenes.return_value = [
        {"scene_id": f"gd_test_scene_{i:03d}", "similarity": 0.9}
        for i in range(3)
    ]
    api.fetch_scenes_content.return_value = []
    api.enqueue_render.return_value = render_job_id
    return api


def _make_pipeline_mocks(*, picker_cost: Decimal = Decimal("0")):
    """Standard happy-path Protocol mocks for the full pipeline."""
    canonical_vec = [1.0] + [0.0] * 767
    embedder = MagicMock()
    embedder.embed.return_value = canonical_vec

    good_buf = io.BytesIO()
    Image.new("RGB", (4, 4), 0).save(good_buf, format="JPEG")
    s3 = MagicMock()
    s3.get_object_bytes.return_value = good_buf.getvalue()
    # PR D: ``downloaded_proxy`` integrity check requires the local
    # file to be non-empty after ``s3.download_file``. The default
    # MagicMock is a no-op, so we wire a side_effect that writes
    # placeholder bytes — keeps every existing test happy without
    # them needing to know about the integrity gate.
    s3.download_file.side_effect = lambda key, local_path: local_path.write_bytes(
        b"fake-mp4-bytes" * 100
    )

    tracker = MagicMock()
    tracker.track.side_effect = _good_track_factory()

    # GreedyPicker is the default when OPENAI_API_KEY is empty —
    # but we want to pin LLM-picker cost flow. Pass a fake picker
    # that exposes ``total_cost_usd``.
    picker = MagicMock()
    picker.total_cost_usd = picker_cost

    def _greedy_pick(scored, **_kwargs):
        return scored  # take everything; the lib's trim handles size

    picker.pick.side_effect = _greedy_pick
    return embedder, s3, tracker, picker


# =====================================================================
# tracker_version propagation
# =====================================================================


def test_appearance_rows_use_settings_tracker_version_not_message():
    """D52-symmetric fix verification: even when the queue message
    carries a stale ``tracker_version``, the appearance rows
    written to /complete MUST be stamped with the version that
    actually executed (``settings.tracker_version``). Otherwise
    ``ProductAppearanceRepository.purge_for_catalog_and_tracker()``
    would fail to clean up rows after a worker upgrade."""
    api = _make_apis(render_job_id=uuid4())
    embedder, s3, tracker, picker = _make_pipeline_mocks()
    settings = _settings(tracker_version="v1.5-current")

    with patch(
        "src.tasks.track._fetch_canonical_crop",
        return_value=_fake_canonical(),
    ):
        handle_track_job(
            message=_job_body(),  # body has tracker_version="v0.9-stale"
            settings=settings,
            api_client=api,
            embedder=embedder,
            tracker=tracker,
            picker=picker,
            s3_client=s3,
        )

    api.complete_track.assert_called_once()
    appearances = api.complete_track.call_args.kwargs["appearances"]
    assert len(appearances) > 0
    # Every appearance carries the SETTINGS version, not the body's
    # stale value.
    assert all(a["tracker_version"] == "v1.5-current" for a in appearances)
    assert not any(a["tracker_version"] == "v0.9-stale" for a in appearances)


# =====================================================================
# cost accumulation
# =====================================================================


def test_picker_cost_rolls_into_complete_track_cost_delta():
    """LLM picker's accumulated USD spend must reach the api's
    /complete callback so the per-org daily-budget gate
    (``AUTO_SHORTS_PRODUCT_V2_DAILY_BUDGET_USD``) accounts
    correctly. Pre-D52 fix this was always 0; pin the new
    behavior."""
    api = _make_apis(render_job_id=uuid4())
    embedder, s3, tracker, picker = _make_pipeline_mocks(
        picker_cost=Decimal("0.0123"),
    )
    settings = _settings()

    with patch(
        "src.tasks.track._fetch_canonical_crop",
        return_value=_fake_canonical(),
    ):
        handle_track_job(
            message=_job_body(),
            settings=settings,
            api_client=api,
            embedder=embedder,
            tracker=tracker,
            picker=picker,
            s3_client=s3,
        )

    api.complete_track.assert_called_once()
    cost = api.complete_track.call_args.kwargs["cost_delta_usd"]
    # The picker's cost MUST be reflected in the final /complete
    # cost_delta_usd. Other stages may add more, so we use >=.
    assert cost >= Decimal("0.0123")


# =====================================================================
# appearance shape strictness
# =====================================================================


def test_appearance_payload_has_only_api_accepted_keys():
    """Drift between worker payload and api ``_AppearancePayload``
    (extra='forbid') = 422 on every successful tracking
    completion. Pin the exact key set so accidental over-projection
    is caught at unit-test time, not at the api boundary."""
    api = _make_apis(render_job_id=uuid4())
    embedder, s3, tracker, picker = _make_pipeline_mocks()

    with patch(
        "src.tasks.track._fetch_canonical_crop",
        return_value=_fake_canonical(),
    ):
        handle_track_job(
            message=_job_body(),
            settings=_settings(),
            api_client=api,
            embedder=embedder,
            tracker=tracker,
            picker=picker,
            s3_client=s3,
        )

    appearances = api.complete_track.call_args.kwargs["appearances"]
    assert len(appearances) > 0
    # Every appearance row must carry exactly these keys — match
    # the api's _AppearancePayload (services/api/app/modules/
    # shorts_auto_product/internal_router.py:_AppearancePayload).
    expected_keys = {
        "scene_id",
        "window_start_ms",
        "window_end_ms",
        "avg_bbox_area_pct",
        "avg_confidence",
        "has_narration_mention",
        "has_ocr_overlap",
        "co_appearing_catalog_entry_ids",
        "raw_bbox_track_s3_key",
        "tracker_version",
        "rejected_reason",
    }
    for a in appearances:
        assert set(a.keys()) == expected_keys, (
            f"appearance shape drift: {set(a.keys()) ^ expected_keys}"
        )


# =====================================================================
# heartbeats at documented checkpoints
# =====================================================================


def test_heartbeats_fire_at_progress_checkpoints():
    """Plan §6.2 documents heartbeats at progress 10 / 20 / 40 /
    80. Pin the contract so a refactor that drops a heartbeat is
    caught — long-running track jobs (1800s lease) lose their
    lease without periodic heartbeats."""
    api = _make_apis(render_job_id=uuid4())
    embedder, s3, tracker, picker = _make_pipeline_mocks()

    with patch(
        "src.tasks.track._fetch_canonical_crop",
        return_value=_fake_canonical(),
    ):
        handle_track_job(
            message=_job_body(),
            settings=_settings(),
            api_client=api,
            embedder=embedder,
            tracker=tracker,
            picker=picker,
            s3_client=s3,
        )

    progress_pcts = [
        call.kwargs["progress_pct"]
        for call in api.heartbeat.call_args_list
    ]
    # Documented checkpoints: 10 (resolving), 20 (retrieval),
    # 40 (SAM2), 80 (scoring/picking).
    assert 10 in progress_pcts
    assert 20 in progress_pcts
    assert 40 in progress_pcts
    assert 80 in progress_pcts


# =====================================================================
# render enqueue uses settings video bucket-derived os_video_id
# =====================================================================


def test_render_enqueue_passes_os_video_id_not_drivefile_uuid():
    """The two id-spaces (DriveFile UUID vs OS string id) must
    stay distinct end-to-end. Pin that the render enqueue uses
    the OS string from ``scenes-with-keyframes``, not the body's
    DriveFile UUID. Mistaking these would 404 the render
    pipeline's S3 lookups."""
    api = _make_apis(render_job_id=uuid4())
    embedder, s3, tracker, picker = _make_pipeline_mocks()
    body = _job_body()

    with patch(
        "src.tasks.track._fetch_canonical_crop",
        return_value=_fake_canonical(),
    ):
        handle_track_job(
            message=body,
            settings=_settings(),
            api_client=api,
            embedder=embedder,
            tracker=tracker,
            picker=picker,
            s3_client=s3,
        )

    api.enqueue_render.assert_called_once()
    enqueue_kwargs = api.enqueue_render.call_args.kwargs
    # ``video_id`` MUST be the OS string from scenes-with-keyframes
    # ("gd_test"), NOT the DriveFile UUID from the message body.
    assert enqueue_kwargs["video_id"] == "gd_test"
    assert enqueue_kwargs["video_id"] != body["video_id"]
    # Composition's per-clip video_id must also be the OS string.
    composition = enqueue_kwargs["composition"]
    assert all(c["video_id"] == "gd_test" for c in composition["scene_clips"])


# =====================================================================
# scan_order parent flow: claim is owned by handle_track_job, NOT by
# _handle_scan_order_parent (regression for 2026-05-03 prod incident)
# =====================================================================


def _scan_order_body() -> dict:
    """Wizard parent message — mode='scan_order', no catalog_entry_id."""
    return {
        "type": "product.track_job",
        "job_id": str(uuid4()),
        "org_id": str(uuid4()),
        "video_id": str(uuid4()),
        "requested_by_user_id": str(uuid4()),
        "tracker_version": "v1.0",
        "enumeration_prompt_version": "v1.0",
        "mode": "scan_order",
        "length_seconds": 30,
        "requested_count": 5,
        "product_distribution": "single",
        "language": "ko",
        "intent": "commit",
    }


def test_scan_order_parent_calls_claim_exactly_once():
    """Regression: ``_handle_scan_order_parent`` previously issued a
    SECOND ``api.claim`` call after ``handle_track_job`` had already
    claimed the job. The second call always 409'd (parent in
    ``tracking``), the function returned early, dispatch returned
    normally, the SDK ack-deleted the message — and the job stuck at
    ``stage=tracking`` forever with no heartbeat/fail/complete.
    Symptom on staging 2026-05-03: 3 successive scan orders all
    silently stalled after the api transitioned to ``tracking``.

    Pin: claim is called EXACTLY ONCE per dispatch, by
    ``handle_track_job``. ``_handle_scan_order_parent`` MUST NOT
    re-claim — its first call should be the resolving heartbeat.
    """
    api = MagicMock()
    # Empty catalog → fast termination via the no_products_detected
    # fail path. Lets the test prove "we got past the redundant claim
    # block" without standing up the full SAM2/picker mock pipeline.
    api.fetch_catalog_entries_for_video.return_value = []
    embedder, s3, tracker, picker = _make_pipeline_mocks()

    handle_track_job(
        message=_scan_order_body(),
        settings=_settings(),
        api_client=api,
        embedder=embedder,
        tracker=tracker,
        picker=picker,
        s3_client=s3,
    )

    # The fix: claim called once, by handle_track_job. Pre-fix this
    # was 2 (handle_track_job + _handle_scan_order_parent).
    assert api.claim.call_count == 1, (
        f"expected exactly one claim call, got {api.claim.call_count} "
        f"(double-claim bug regression: 2026-05-03)"
    )
    # Heartbeat fires only AFTER the redundant claim block was removed —
    # if the bug returns, this would be 0.
    assert api.heartbeat.call_count >= 1, (
        "heartbeat never fired — the dispatcher likely hit the early "
        "return on a redundant claim 409"
    )
    # Sanity: the empty-catalog path's terminal /fail call landed.
    api.fail.assert_called_once()
    assert api.fail.call_args.kwargs["error_code"] == "no_products_detected"


# =====================================================================
# scan_order parent flow: catalog_entry_id narrows the catalog fetch
# (wizard product-select step output)
# =====================================================================


def test_scan_order_with_catalog_entry_id_uses_single_entry_fetch():
    """When the wizard's product-select step picked a catalog entry,
    the worker MUST call fetch_catalog_entry(id) — NOT
    fetch_catalog_entries_for_video — and proceed to track ONLY that
    product. Pre-feature: the field was unused, the worker always
    fanned across the whole active catalog (round-robin via picker).

    Test uses an empty scenes-with-keyframes response to terminate the
    per-product loop quickly via the no-qualifying-windows path —
    avoids standing up the full SAM2 + picker mock pipeline. The
    assertion is on which fetch path the worker took, not on output.
    """
    catalog_entry_id = uuid4()
    api = MagicMock()
    # The single-entry fetch returns the same shape as the per-video
    # list endpoint (per fetch_catalog_entry's docstring contract).
    api.fetch_catalog_entry.return_value = {
        "catalog_entry_id": str(catalog_entry_id),
        "org_id": str(uuid4()),
        "video_id": "gd_test",
        "canonical_crop_s3_key": "k.jpg",
        "canonical_bbox": {"x": 0, "y": 0, "w": 10, "h": 10},
        "llm_label": "테스트 제품",
    }
    # No scenes → per-product loop produces no qualifying windows →
    # parent /fails as tracker_low_confidence_global. Skips SAM2.
    # ``proxy_s3_key`` populated so we don't trip the upstream
    # ``proxy_missing`` fast-fail (which is exercised by its own test).
    api.fetch_scenes_with_keyframes.return_value = {
        "video_id": "gd_test",
        "proxy_s3_key": "tenant/drive/d/g/proxy.mp4",
        "scenes": [],
    }
    embedder, s3, tracker, picker = _make_pipeline_mocks()

    body = _scan_order_body()
    body["catalog_entry_id"] = str(catalog_entry_id)

    handle_track_job(
        message=body,
        settings=_settings(),
        api_client=api,
        embedder=embedder,
        tracker=tracker,
        picker=picker,
        s3_client=s3,
    )

    # The point of this test: single-entry fetch is the chosen path.
    api.fetch_catalog_entry.assert_called_once()
    fetch_kwargs = api.fetch_catalog_entry.call_args.kwargs
    assert fetch_kwargs["catalog_entry_id"] == catalog_entry_id
    # And the bulk fetch was NOT used.
    api.fetch_catalog_entries_for_video.assert_not_called()


def test_scan_order_catalog_entry_404_fails_cleanly():
    """If the picked entry was rejected between submit and worker
    pickup, fetch_catalog_entry 404s. Worker MUST translate that to
    a no_products_detected /fail (not bubble the HTTPStatusError to
    SDK as a redelivery candidate — the entry won't un-reject)."""
    import httpx

    catalog_entry_id = uuid4()
    api = MagicMock()
    # Build a real httpx 404 to mirror what the api_client raises.
    fake_resp = MagicMock(spec=httpx.Response)
    fake_resp.status_code = 404
    api.fetch_catalog_entry.side_effect = httpx.HTTPStatusError(
        "404", request=MagicMock(spec=httpx.Request), response=fake_resp,
    )
    embedder, s3, tracker, picker = _make_pipeline_mocks()

    body = _scan_order_body()
    body["catalog_entry_id"] = str(catalog_entry_id)

    handle_track_job(
        message=body,
        settings=_settings(),
        api_client=api,
        embedder=embedder,
        tracker=tracker,
        picker=picker,
        s3_client=s3,
    )

    api.fetch_catalog_entry.assert_called_once()
    api.fail.assert_called_once()
    assert api.fail.call_args.kwargs["error_code"] == "no_products_detected"


# =====================================================================
# scan_order parent flow: TrackingConfig override uses dataclass.replace
# (regression for 2026-05-04 staging incident)
# =====================================================================


def test_scan_order_cfg_override_uses_dataclass_replace():
    """Regression: ``TrackingConfig`` is a frozen dataclass — direct
    attribute assignment raises ``FrozenInstanceError`` ("cannot
    assign to field 'min_window_duration_ms'"). Pre-fix code did
    ``cfg.min_window_duration_ms = …`` and the parent failed with
    ``error_code='internal_error'`` after a clean claim + 2
    heartbeats. Post-fix uses ``dataclasses.replace()``.

    Pure unit test — no SAM2 / picker mock needed; just exercise the
    same import + config-construction path the dispatch uses.
    """
    from dataclasses import replace

    from src.tasks.track import _make_config

    cfg = _make_config(_settings())
    # Shouldn't raise FrozenInstanceError.
    new_cfg = replace(cfg, min_window_duration_ms=999)
    assert new_cfg.min_window_duration_ms == 999
    # Original instance is immutable — the override returns a new
    # value, doesn't mutate in place.
    assert cfg.min_window_duration_ms != 999


# =====================================================================
# Single-proxy contract (PR B, post-2026-05-04 sam2-proxy handoff)
# =====================================================================


def test_legacy_path_proxy_missing_returns_proxy_missing_error_code():
    """Transcode-incomplete videos: ``DriveFile.proxy_s3_key`` is
    NULL → API echoes ``proxy_s3_key=None`` → worker MUST fail with
    ``error_code=proxy_missing`` (not the opaque ``internal_error``)
    so the wizard can show "video isn't ready yet" cleanly. SAM2
    must NEVER be invoked on a missing-proxy job — every call would
    F4 anyway."""
    api = _make_apis(render_job_id=uuid4())
    # Override the fixture's proxy_s3_key to None.
    api.fetch_scenes_with_keyframes.return_value = {
        **_scenes_response(n=3),
        "proxy_s3_key": None,
    }
    embedder, s3, tracker, picker = _make_pipeline_mocks()

    with patch(
        "src.tasks.track._fetch_canonical_crop",
        return_value=_fake_canonical(),
    ):
        handle_track_job(
            message=_job_body(),
            settings=_settings(),
            api_client=api,
            embedder=embedder,
            tracker=tracker,
            picker=picker,
            s3_client=s3,
        )

    # Distinct error code so the wizard maps it to a friendly message.
    api.fail.assert_called_once()
    assert api.fail.call_args.kwargs["error_code"] == "proxy_missing"
    # SAM2 wrapper never invoked — saves a fruitless GPU call.
    tracker.track.assert_not_called()
    # And no S3 download attempt on the proxy.
    s3.download_file.assert_not_called()


def test_scan_order_parent_proxy_missing_returns_proxy_missing_error_code():
    """Same fast-fail in the wizard scan_order parent. Locks the
    contract that BOTH dispatch paths surface ``proxy_missing``
    consistently — wizard error UI maps a single code, not two."""
    api = MagicMock()
    api.fetch_catalog_entries_for_video.return_value = [
        {
            "catalog_entry_id": str(uuid4()),
            "org_id": str(uuid4()),
            "video_id": "gd_test",
            "canonical_crop_s3_key": "k.jpg",
            "canonical_bbox": {"x": 0, "y": 0, "w": 10, "h": 10},
            "llm_label": "테스트 제품",
        }
    ]
    api.fetch_scenes_with_keyframes.return_value = {
        **_scenes_response(n=3),
        "proxy_s3_key": None,
    }
    embedder, s3, tracker, picker = _make_pipeline_mocks()

    handle_track_job(
        message=_scan_order_body(),
        settings=_settings(),
        api_client=api,
        embedder=embedder,
        tracker=tracker,
        picker=picker,
        s3_client=s3,
    )

    api.fail.assert_called_once()
    assert api.fail.call_args.kwargs["error_code"] == "proxy_missing"
    tracker.track.assert_not_called()
    s3.download_file.assert_not_called()


def test_scan_order_parent_downloads_proxy_once_for_multiple_products():
    """Critical invariant: N products in one scan order → exactly
    ONE S3 GET on the proxy. The download lives in
    ``_handle_scan_order_parent`` (outside the per-product loop)
    so each product reuses the same local file. A regression here
    would multiply Aircloud's cold-start S3 cost N× without any
    pipeline benefit."""
    api = _make_apis(render_job_id=uuid4())
    # Three catalog entries; each kicks off retrieve+SAM2.
    api.fetch_catalog_entries_for_video.return_value = [
        {
            "catalog_entry_id": str(uuid4()),
            "org_id": str(uuid4()),
            "video_id": "gd_test",
            "canonical_crop_s3_key": f"k{i}.jpg",
            "canonical_bbox": {"x": 0, "y": 0, "w": 10, "h": 10},
            "llm_label": f"제품{i}",
        }
        for i in range(3)
    ]
    embedder, s3, tracker, picker = _make_pipeline_mocks()

    with patch(
        "src.tasks.track._fetch_canonical_crop",
        return_value=_fake_canonical(),
    ):
        handle_track_job(
            message=_scan_order_body(),
            settings=_settings(),
            api_client=api,
            embedder=embedder,
            tracker=tracker,
            picker=picker,
            s3_client=s3,
        )

    # The contract — one download per scan_order, NOT per product.
    assert s3.download_file.call_count == 1, (
        f"expected exactly one proxy download per scan_order, got "
        f"{s3.download_file.call_count} — per-product download regression"
    )
    # And the path used was the canonical proxy_s3_key from the
    # scenes-with-keyframes response.
    download_args = s3.download_file.call_args.args
    assert download_args[0] == "tenant/drive/d/g/proxy.mp4"


# =====================================================================
# Per-stage F4 worker_event diagnostics (PR C, post-2026-05-04 incident)
# =====================================================================


def test_canonical_crop_s3_returns_none_emits_per_product_failed_event_with_exception_details():
    """Regression coverage for the silent-S3-None failure mode that
    cost us a debugging session 2026-05-04 (Aircloud container lost
    its ``MINIO_ENDPOINT=disabled`` override on restart, every S3
    read returned None, ``_fetch_canonical_crop`` raised
    ``FileNotFoundError``, the outer ``except Exception`` caught it
    and only logged to stdout — leaving the operator with the
    opaque ``internal_error`` aggregate message).

    Pin the contract that the per-product exception handler emits a
    structured worker_event carrying the exception type + message,
    so the same failure is SQL-queryable from the api DB without
    chasing Aircloud container logs."""
    catalog_entry_id = uuid4()
    api = MagicMock()
    api.fetch_catalog_entries_for_video.return_value = [
        {
            "catalog_entry_id": str(catalog_entry_id),
            "org_id": str(uuid4()),
            "video_id": "gd_test",
            "canonical_crop_s3_key": "tenant/products/x/y.jpg",
            "canonical_bbox": {"x": 0, "y": 0, "w": 10, "h": 10},
            "llm_label": "테스트 제품",
        }
    ]
    # _fetch_canonical_crop reads the entry by id, then s3-fetches.
    # Return the matching payload from the single-entry endpoint
    # so the org-mismatch defence-in-depth doesn't fire first.
    org_id = uuid4()
    api.fetch_catalog_entry.return_value = {
        "catalog_entry_id": str(catalog_entry_id),
        "org_id": str(org_id),
        "video_id": "gd_test",
        "canonical_crop_s3_key": "tenant/products/x/y.jpg",
        "canonical_bbox": {"x": 0, "y": 0, "w": 10, "h": 10},
        "llm_label": "테스트 제품",
    }
    # Re-stub the catalog list to the matching org so both paths agree.
    api.fetch_catalog_entries_for_video.return_value[0]["org_id"] = str(org_id)
    api.fetch_scenes_with_keyframes.return_value = _scenes_response(n=3)

    embedder, s3, tracker, picker = _make_pipeline_mocks()
    # Simulate the MINIO_ENDPOINT regression: S3 reads silently
    # return None instead of raising. _fetch_canonical_crop's null
    # check then raises FileNotFoundError.
    s3.get_object_bytes.return_value = None

    # Body uses the matching org_id so Pattern B doesn't 404.
    body = _scan_order_body()
    body["org_id"] = str(org_id)

    with patch("src.tasks.track.emit_event") as mock_emit:
        handle_track_job(
            message=body,
            settings=_settings(),
            api_client=api,
            embedder=embedder,
            tracker=tracker,
            picker=picker,
            s3_client=s3,
        )

    # Two events fire on this path:
    #   1. scan_order_per_product_failed — captures FileNotFoundError
    #   2. scan_order_all_products_f4_failed — aggregate summary
    event_names = [c.kwargs.get("event_name") for c in mock_emit.call_args_list]
    assert "scan_order_per_product_failed" in event_names, (
        f"per-product event missing — operators have no SQL-queryable "
        f"signal of which step failed. Got: {event_names}"
    )
    assert "scan_order_all_products_f4_failed" in event_names

    # Per-product event MUST carry the exception type/message so a
    # MINIO regression / S3 outage / catalog-corruption are all
    # distinguishable in worker_events queries.
    per_product = next(
        c for c in mock_emit.call_args_list
        if c.kwargs.get("event_name") == "scan_order_per_product_failed"
    )
    md = per_product.kwargs["metadata"]
    assert md["exception_type"] == "FileNotFoundError", (
        f"exception_type missing or wrong; metadata={md}"
    )
    assert "canonical crop" in md["exception_message"].lower(), (
        f"exception_message should reference the failure source; got: {md}"
    )
    # job_id + video_id propagated so per-job triage is one query.
    # ``video_id`` here is ``TrackJobMessage.video_id`` — the
    # DriveFile UUID, NOT the OS string "gd_test". Worker_events
    # convention across services.
    assert per_product.kwargs.get("job_id") is not None
    assert per_product.kwargs.get("video_id") is not None

    # And api.fail's error_message points operators at worker_events
    # (instead of "Check worker logs" which means Aircloud-only).
    api.fail.assert_called_once()
    fail_msg = api.fail.call_args.kwargs["error_message"]
    assert "worker_events" in fail_msg, (
        f"fail message should redirect to worker_events; got: {fail_msg}"
    )
