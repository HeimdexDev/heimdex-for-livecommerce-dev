"""F4 tests — distinguish stage-wide failure from "no qualifying
appearances" in :func:`handle_track_job`.

Codex finding F4: the Phase 3a pipeline lib silently catches per-scene
errors (keyframe fetch / SAM2 track) and continues. If every scene
errors due to a systemic issue (S3 outage, broken SigLIP2 weights,
SAM2 OOM), the worker pre-fix reported the job as "no qualifying
appearances" via ``/complete`` — hiding a real fault from the user.

Post-fix, the worker counts attempts vs. failures via wrappers around
the injected protocols. When ``attempted > 0 and failed == attempted``,
``/fail`` is called with ``error_code="internal_error"`` and the
stage detail in ``error_message`` (the API ``_FailRequest`` enum has
no dedicated ``all_scenes_failed`` literal). The "no qualifying
windows" path also uses ``/fail``, with
``error_code="tracker_low_confidence_global"`` — the API's
``_CompleteRequest`` 400s on empty ``appearances``.

These tests stub the canonical-crop scaffold (still raises
``NotImplementedError`` in main code per Phase 3c-A) so the F4 logic
can be exercised end-to-end before Phase 3c-B lands the real endpoint.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from PIL import Image

from heimdex_media_pipelines.product_track.sam2_pass import BBoxXYWH

from src.settings import WorkerSettings
from src.tasks.track import (
    _CountingEmbedder,
    _CountingKeyframeFetcher,
    _CountingSam2Tracker,
    handle_track_job,
)


# ─── helpers ─────────────────────────────────────────────────────────


def _settings() -> WorkerSettings:
    return WorkerSettings(
        product_v2_enabled=True,
        sqs_product_track_queue_url="https://sqs.test/q",
        drive_internal_api_key="test-token",
        drive_api_base_url="http://api:8000",
        drive_s3_bucket="test-bucket",
        worker_id="test-worker",
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
        "tracker_version": "v1.0",
        "enumeration_prompt_version": "v1.0",
    }


def _fake_canonical():
    """Stand-in for the Phase 3c-B catalog-entry fetch.

    Matches ``_fetch_canonical_crop``'s real return shape:
    ``(canonical_crop, canonical_bbox, llm_label)``."""
    img = Image.new("RGB", (256, 256), (200, 100, 50))
    bbox = BBoxXYWH(x=10, y=10, width=50, height=50)
    return img, bbox, "테스트 제품"


def _scenes_response(n: int = 3) -> dict:
    return {
        "video_id": "gd_test",
        "scenes": [
            {"scene_id": f"gd_test_scene_{i:03d}", "keyframe_s3_key": f"k{i}.jpg"}
            for i in range(n)
        ],
    }


# ─── _CountingEmbedder ──────────────────────────────────────────────


class TestCountingEmbedder:
    def test_canonical_succeeds_then_all_per_scene_fail(self):
        """Canonical embed (first call) returns; every subsequent
        per-scene call raises. ``per_scene_all_failed`` is True."""
        attempts = {"n": 0}

        def _side_effect(image):
            attempts["n"] += 1
            if attempts["n"] == 1:
                return [0.1] * 768
            raise RuntimeError("siglip down")

        inner = MagicMock()
        inner.embed.side_effect = _side_effect
        wrapped = _CountingEmbedder(inner)

        # Canonical (success).
        wrapped.embed(Image.new("RGB", (1, 1)))
        assert wrapped.attempted == 1
        assert wrapped.failed == 0
        assert wrapped.per_scene_all_failed() is False

        # 3 per-scene attempts, all raise.
        for _ in range(3):
            with pytest.raises(RuntimeError):
                wrapped.embed(Image.new("RGB", (1, 1)))
        assert wrapped.attempted == 4
        assert wrapped.failed == 3
        assert wrapped.per_scene_attempted == 3
        assert wrapped.per_scene_all_failed() is True

    def test_canonical_only_no_per_scene_is_not_all_failed(self):
        """Just the canonical embed — no per-scene calls — must not
        trip the ``per_scene_all_failed`` check (would be a false
        positive on the empty-coarse path)."""
        inner = MagicMock()
        inner.embed.return_value = [0.1] * 768
        wrapped = _CountingEmbedder(inner)
        wrapped.embed(Image.new("RGB", (1, 1)))
        assert wrapped.per_scene_all_failed() is False


# ─── _CountingKeyframeFetcher ───────────────────────────────────────


class TestCountingKeyframeFetcher:
    def test_increments_attempted_on_success(self):
        inner = MagicMock()
        inner.fetch_scene_keyframe.return_value = Image.new("RGB", (1, 1))
        wrapped = _CountingKeyframeFetcher(inner)
        wrapped.fetch_scene_keyframe("s1")
        assert wrapped.attempted == 1
        assert wrapped.failed == 0
        assert wrapped.all_attempts_failed is False

    def test_counts_failure_and_reraises(self):
        inner = MagicMock()
        inner.fetch_scene_keyframe.side_effect = RuntimeError("S3 down")
        wrapped = _CountingKeyframeFetcher(inner)
        with pytest.raises(RuntimeError):
            wrapped.fetch_scene_keyframe("s1")
        assert wrapped.attempted == 1
        assert wrapped.failed == 1
        assert wrapped.all_attempts_failed is True

    def test_zero_attempts_is_not_all_failed(self):
        wrapped = _CountingKeyframeFetcher(MagicMock())
        # ``all_attempts_failed`` MUST require attempted > 0 — otherwise
        # an empty coarse-candidate list (a legitimate "no scenes
        # matched" outcome) would route to /fail.
        assert wrapped.all_attempts_failed is False


# ─── _CountingSam2Tracker ───────────────────────────────────────────


class TestCountingSam2Tracker:
    def _kwargs(self):
        return dict(
            scene_id="s1",
            anchor_bbox=BBoxXYWH(x=0, y=0, width=10, height=10),
            anchor_keyframe=Image.new("RGB", (1, 1)),
            scene_video_url="s3://x",
            sample_fps=5,
        )

    def test_increments_attempted_on_success(self):
        inner = MagicMock()
        inner.track.return_value = []
        wrapped = _CountingSam2Tracker(inner)
        wrapped.track(**self._kwargs())
        assert wrapped.attempted == 1
        assert wrapped.failed == 0

    def test_counts_failure_and_reraises(self):
        inner = MagicMock()
        inner.track.side_effect = RuntimeError("CUDA OOM")
        wrapped = _CountingSam2Tracker(inner)
        with pytest.raises(RuntimeError):
            wrapped.track(**self._kwargs())
        assert wrapped.failed == 1
        assert wrapped.all_attempts_failed is True


# ─── handle_track_job F4 paths ──────────────────────────────────────


class TestHandleTrackJobAllScenesFailed:
    """End-to-end F4 paths via mock injection past the Phase 3c-A
    canonical-crop scaffold."""

    def _make_api(self) -> MagicMock:
        api = MagicMock()
        api.fetch_scenes_with_keyframes.return_value = _scenes_response(n=3)
        api.find_similar_scenes.return_value = [
            {"scene_id": f"gd_test_scene_{i:03d}", "similarity": 0.9}
            for i in range(3)
        ]
        return api

    def test_all_keyframe_fetches_fail_calls_fail_with_internal_error(self):
        """3 candidate scenes from coarse retrieval, every keyframe
        fetch raises (S3 outage simulation). Worker MUST call /fail
        with ``internal_error`` + a stage label in the message, NOT
        /complete. ``error_code`` is ``internal_error`` because the
        API's ``_FailRequest`` enum doesn't have a dedicated
        ``all_scenes_failed`` literal."""
        api = self._make_api()

        # Embedder produces a stable canonical vec; per-scene re-embed
        # would be reached only AFTER keyframe fetch succeeds. Here all
        # fetches fail so the embedder is only called once for the
        # canonical crop.
        embedder = MagicMock()
        embedder.embed.return_value = [0.1] * 768

        # S3 client raises on every keyframe fetch.
        s3 = MagicMock()
        s3.get_object_bytes.side_effect = RuntimeError("S3 unavailable")

        with patch(
            "src.tasks.track._fetch_canonical_crop",
            return_value=_fake_canonical(),
        ):
            handle_track_job(
                message=_job_body(),
                settings=_settings(),
                api_client=api,
                embedder=embedder,
                s3_client=s3,
            )

        # /fail called; /complete_track NOT called.
        api.fail.assert_called_once()
        kwargs = api.fail.call_args.kwargs
        assert kwargs["error_code"] == "internal_error"
        assert "keyframe_fetch" in kwargs["error_message"]
        api.complete_track.assert_not_called()

    def test_empty_coarse_candidates_calls_fail_no_qualifying(self):
        """0 coarse candidates → keyframe fetcher never called →
        ``attempted=0`` → must NOT trip the F4 stage-failure path.
        Routes to /fail with ``tracker_low_confidence_global`` instead
        of /complete with empty appearances (the API rejects empty
        appearances on tracking /complete with a 400)."""
        api = self._make_api()
        api.find_similar_scenes.return_value = []

        embedder = MagicMock()
        embedder.embed.return_value = [0.1] * 768
        s3 = MagicMock()

        with patch(
            "src.tasks.track._fetch_canonical_crop",
            return_value=_fake_canonical(),
        ):
            handle_track_job(
                message=_job_body(),
                settings=_settings(),
                api_client=api,
                embedder=embedder,
                s3_client=s3,
            )

        api.complete_track.assert_not_called()
        api.fail.assert_called_once()
        kwargs = api.fail.call_args.kwargs
        assert kwargs["error_code"] == "tracker_low_confidence_global"

    def test_partial_keyframe_failure_does_not_trip_f4(self):
        """3 candidates, 2 keyframes fail to fetch, 1 succeeds but
        precise-similarity filter rejects it. ``failed=2``,
        ``attempted=3`` — F4 condition (``failed == attempted``) is
        NOT met. With no candidates surviving the precise threshold,
        ``annotated`` is empty so ``_terminate_no_render`` falls
        through to /fail with ``tracker_low_confidence_global``
        (API rejects empty appearances on /complete)."""
        api = self._make_api()

        canonical_vec = [0.1] * 768
        # The 1 successful re-embed yields a near-orthogonal vector
        # (low similarity) → filtered out by the precise threshold.
        embedder = MagicMock()
        embedder.embed.side_effect = [canonical_vec, [0.0] * 767 + [1.0]]

        # S3: 2 keys raise, 1 returns valid jpeg bytes.
        import io as _io
        good_buf = _io.BytesIO()
        Image.new("RGB", (4, 4), 0).save(good_buf, format="JPEG")
        good_bytes = good_buf.getvalue()
        s3 = MagicMock()
        s3.get_object_bytes.side_effect = [
            RuntimeError("missing"),
            good_bytes,
            RuntimeError("missing"),
        ]

        with patch(
            "src.tasks.track._fetch_canonical_crop",
            return_value=_fake_canonical(),
        ):
            handle_track_job(
                message=_job_body(),
                settings=_settings(),
                api_client=api,
                embedder=embedder,
                s3_client=s3,
            )

        # Partial failure → not the F4 stage-wide path → no
        # ``internal_error``. Falls into the no-qualifying branch.
        api.complete_track.assert_not_called()
        api.fail.assert_called_once()
        kwargs = api.fail.call_args.kwargs
        assert kwargs["error_code"] == "tracker_low_confidence_global"

    def test_all_per_scene_embeds_fail_calls_fail_with_internal_error(self):
        """3 candidate scenes, every keyframe downloads OK, but every
        per-scene SigLIP2 embed call raises (e.g. corrupted HF cache,
        bad weights deploy). Pre-fix this fell to
        ``tracker_low_confidence_global`` because the lib swallows
        per-scene embed exceptions; post-fix the embedder counter
        catches it as a stage-wide outage and routes to /fail with
        ``internal_error``."""
        api = self._make_api()

        # First call (canonical) succeeds; every subsequent per-scene
        # call raises.
        canonical_vec = [0.1] * 768

        def _embed_side_effect(image):
            # MagicMock side_effect doesn't track call count for us
            # the way we need — emulate manually.
            _embed_side_effect.calls += 1
            if _embed_side_effect.calls == 1:
                return canonical_vec
            raise RuntimeError("SigLIP2 weights corrupted")

        _embed_side_effect.calls = 0
        embedder = MagicMock()
        embedder.embed.side_effect = _embed_side_effect

        # S3 returns valid jpeg bytes for every keyframe.
        import io as _io
        good_buf = _io.BytesIO()
        Image.new("RGB", (4, 4), 0).save(good_buf, format="JPEG")
        good_bytes = good_buf.getvalue()
        s3 = MagicMock()
        s3.get_object_bytes.return_value = good_bytes

        with patch(
            "src.tasks.track._fetch_canonical_crop",
            return_value=_fake_canonical(),
        ):
            handle_track_job(
                message=_job_body(),
                settings=_settings(),
                api_client=api,
                embedder=embedder,
                s3_client=s3,
            )

        api.fail.assert_called_once()
        kwargs = api.fail.call_args.kwargs
        assert kwargs["error_code"] == "internal_error"
        assert "siglip2_embed" in kwargs["error_message"]
        api.complete_track.assert_not_called()

    def test_scenes_lookup_404_calls_fail_with_video_not_found(self):
        """``GET /internal/videos/{file_id}/scenes-with-keyframes``
        returning 404 means the DriveFile was deleted or failed an
        org check between enqueue and processing. The worker MUST
        surface that as ``video_not_found`` (matches enumerate-worker)
        instead of letting the dispatcher report a generic
        ``internal_error``."""
        import httpx

        api = self._make_api()
        # Build a real httpx.HTTPStatusError so the worker can read
        # ``exc.response.status_code``.
        request = httpx.Request("GET", "http://api/internal/videos/x/scenes-with-keyframes")
        response = httpx.Response(404, request=request)
        api.fetch_scenes_with_keyframes.side_effect = httpx.HTTPStatusError(
            "404 Not Found", request=request, response=response,
        )

        embedder = MagicMock()
        embedder.embed.return_value = [0.1] * 768
        s3 = MagicMock()

        with patch(
            "src.tasks.track._fetch_canonical_crop",
            return_value=_fake_canonical(),
        ):
            handle_track_job(
                message=_job_body(),
                settings=_settings(),
                api_client=api,
                embedder=embedder,
                s3_client=s3,
            )

        api.fail.assert_called_once()
        kwargs = api.fail.call_args.kwargs
        assert kwargs["error_code"] == "video_not_found"
        api.complete_track.assert_not_called()

    def test_claim_409_acks_message_without_fail_or_retry(self):
        """The api returns 409 on claim when the job is already
        claimed/completed/cancelled (duplicate or stale SQS
        deliveries). Per api contract: ack the message, do not
        retry. Pre-fix the 409 propagated to the dispatcher's
        generic exception path → /fail attempt (also 409) →
        re-raise → eventual DLQ for what is a no-op. Post-fix the
        worker logs + returns normally so the SDK ack-deletes."""
        import httpx

        api = self._make_api()
        request = httpx.Request("POST", "http://api/internal/products/x/claim")
        response = httpx.Response(409, request=request)
        api.claim.side_effect = httpx.HTTPStatusError(
            "409 Conflict", request=request, response=response,
        )

        embedder = MagicMock()
        embedder.embed.return_value = [0.1] * 768
        s3 = MagicMock()

        with patch(
            "src.tasks.track._fetch_canonical_crop",
            return_value=_fake_canonical(),
        ):
            # MUST NOT raise — worker handles 409 internally so the
            # SDK ack-deletes the message normally.
            handle_track_job(
                message=_job_body(),
                settings=_settings(),
                api_client=api,
                embedder=embedder,
                s3_client=s3,
            )

        # No /fail (we don't own the lease). No /complete either.
        api.fail.assert_not_called()
        api.complete_track.assert_not_called()
        # Heartbeats also skipped — we returned before reaching them.
        api.heartbeat.assert_not_called()

    def test_claim_5xx_propagates_to_dispatcher(self):
        """Non-409 HTTP errors on claim still propagate so the
        dispatcher's generic catch reports ``internal_error``. The
        409 carve-out is the only no-op path."""
        import httpx

        api = self._make_api()
        request = httpx.Request("POST", "http://api/internal/products/x/claim")
        response = httpx.Response(503, request=request)
        api.claim.side_effect = httpx.HTTPStatusError(
            "503 Service Unavailable", request=request, response=response,
        )

        embedder = MagicMock()
        embedder.embed.return_value = [0.1] * 768
        s3 = MagicMock()

        with patch(
            "src.tasks.track._fetch_canonical_crop",
            return_value=_fake_canonical(),
        ):
            with pytest.raises(httpx.HTTPStatusError):
                handle_track_job(
                    message=_job_body(),
                    settings=_settings(),
                    api_client=api,
                    embedder=embedder,
                    s3_client=s3,
                )

    def test_scenes_lookup_5xx_propagates_to_dispatcher(self):
        """Non-404 HTTP errors should propagate so the dispatcher
        catches and reports ``internal_error``. The 404 special-case
        is the only carve-out."""
        import httpx

        api = self._make_api()
        request = httpx.Request("GET", "http://api/internal/videos/x/scenes-with-keyframes")
        response = httpx.Response(503, request=request)
        api.fetch_scenes_with_keyframes.side_effect = httpx.HTTPStatusError(
            "503 Service Unavailable", request=request, response=response,
        )

        embedder = MagicMock()
        embedder.embed.return_value = [0.1] * 768
        s3 = MagicMock()

        with patch(
            "src.tasks.track._fetch_canonical_crop",
            return_value=_fake_canonical(),
        ):
            with pytest.raises(httpx.HTTPStatusError):
                handle_track_job(
                    message=_job_body(),
                    settings=_settings(),
                    api_client=api,
                    embedder=embedder,
                    s3_client=s3,
                )

        # Worker did NOT call /fail itself — the dispatcher's
        # exception catch is responsible for that path.
        api.fail.assert_not_called()

    def test_rejected_only_annotated_completes_with_rejected_appearances(self):
        """SAM2 produces detections that are valid windows but every
        one is rejected by thresholds (low avg_bbox_area_pct, low
        confidence, etc.). ``annotated`` is non-empty (rejected
        rows); ``scored=[]`` because score_windows drops rejected
        windows. Pre-fix this called /fail and dropped the rejected
        data; post-fix it /completes with the rejected appearances
        + ``render_job_id=None`` so the api persists them for
        threshold tuning."""
        api = self._make_api()

        canonical_vec = [1.0] + [0.0] * 767
        embedder = MagicMock()
        embedder.embed.return_value = canonical_vec

        import io as _io
        good_buf = _io.BytesIO()
        Image.new("RGB", (4, 4), 0).save(good_buf, format="JPEG")
        s3 = MagicMock()
        s3.get_object_bytes.return_value = good_buf.getvalue()

        # SAM2 returns one short low-confidence sample per scene.
        # Configured thresholds (min_window_duration_ms=1500,
        # min_avg_confidence=0.7) will reject these on assemble +
        # score; ``annotated`` carries the rejected rows.
        from heimdex_media_pipelines.product_track.sam2_pass import TrackedSample

        def _make_track(*, scene_id, **_kwargs):
            return [
                TrackedSample(
                    frame_timestamp_ms=0,
                    bbox=BBoxXYWH(x=0, y=0, width=20, height=20),
                    mask_confidence=0.5,  # below min_avg_confidence=0.7
                    frame_width=1280,
                    frame_height=720,
                ),
            ]

        tracker = MagicMock()
        tracker.track.side_effect = _make_track

        # API mock returns content for transcripts/ocr fetch.
        api.fetch_scenes_content.return_value = []

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
                s3_client=s3,
            )

        # Should /complete (not /fail) so rejected data is persisted.
        api.fail.assert_not_called()
        api.complete_track.assert_called_once()
        body = api.complete_track.call_args.kwargs
        assert body["render_job_id"] is None
        assert len(body["appearances"]) > 0
        # Rejected rows carry ``rejected_reason`` set; pin that the
        # serializer included it.
        assert any(
            a.get("rejected_reason") is not None
            for a in body["appearances"]
        )

    def test_all_sam2_tracks_fail_calls_fail_with_internal_error(self):
        """Coarse + precise pass produce candidate scenes; SAM2
        tracker raises on every scene. Worker MUST call /fail with
        ``internal_error`` + ``sam2_track`` stage detail, NOT
        /complete."""
        api = self._make_api()

        # Canonical and per-scene embeddings all match (>= precise threshold)
        # so every coarse candidate survives to SAM2.
        canonical_vec = [1.0] + [0.0] * 767
        embedder = MagicMock()
        embedder.embed.return_value = canonical_vec

        # S3 returns valid jpeg bytes for every keyframe.
        import io as _io
        good_buf = _io.BytesIO()
        Image.new("RGB", (4, 4), 0).save(good_buf, format="JPEG")
        good_bytes = good_buf.getvalue()
        s3 = MagicMock()
        s3.get_object_bytes.return_value = good_bytes

        # SAM2 tracker raises on every scene.
        tracker = MagicMock()
        tracker.track.side_effect = RuntimeError("CUDA OOM")

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
                s3_client=s3,
            )

        api.fail.assert_called_once()
        kwargs = api.fail.call_args.kwargs
        assert kwargs["error_code"] == "internal_error"
        assert "sam2_track" in kwargs["error_message"]
        api.complete_track.assert_not_called()
