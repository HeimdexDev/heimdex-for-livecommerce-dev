"""F4 tests — distinguish stage-wide failure from "no qualifying
appearances" in :func:`handle_track_job`.

Codex finding F4: the Phase 3a pipeline lib silently catches per-scene
errors (keyframe fetch / SAM2 track) and continues. If every scene
errors due to a systemic issue (S3 outage, broken SigLIP2 weights,
SAM2 OOM), the worker pre-fix reported the job as "no qualifying
appearances" via ``/complete`` — hiding a real fault from the user.

Post-fix, the worker counts attempts vs. failures via wrappers around
the injected protocols. When ``attempted > 0 and failed == attempted``,
``/fail`` is called with ``error_code="all_scenes_failed"``.

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
    """Stand-in for the Phase 3c-B catalog-entry fetch."""
    img = Image.new("RGB", (256, 256), (200, 100, 50))
    bbox = BBoxXYWH(x=10, y=10, width=50, height=50)
    return img, bbox


def _scenes_response(n: int = 3) -> dict:
    return {
        "video_id": "gd_test",
        "scenes": [
            {"scene_id": f"gd_test_scene_{i:03d}", "keyframe_s3_key": f"k{i}.jpg"}
            for i in range(n)
        ],
    }


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

    def test_all_keyframe_fetches_fail_calls_fail_with_all_scenes_failed(self):
        """3 candidate scenes from coarse retrieval, every keyframe
        fetch raises (S3 outage simulation). Worker MUST call /fail
        with ``all_scenes_failed``, NOT /complete."""
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

        # /fail called with all_scenes_failed; /complete_track NOT called.
        api.fail.assert_called_once()
        kwargs = api.fail.call_args.kwargs
        assert kwargs["error_code"] == "all_scenes_failed"
        assert "keyframe_fetch" in kwargs["error_message"]
        api.complete_track.assert_not_called()

    def test_empty_coarse_candidates_calls_complete_no_qualifying(self):
        """0 coarse candidates → keyframe fetcher never called →
        ``attempted=0`` → must NOT trip the F4 path. /complete with
        empty stitch plan is the correct success outcome."""
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

        api.fail.assert_not_called()
        api.complete_track.assert_called_once()
        body = api.complete_track.call_args.kwargs
        assert body["stitching_plan"] is None
        assert body["render_job_id"] is None

    def test_partial_keyframe_failure_does_not_trip_f4(self):
        """3 candidates, 2 keyframes fail to fetch, 1 succeeds but
        precise-similarity filter rejects it. ``failed=2``,
        ``attempted=3`` — F4 condition (``failed == attempted``) is
        NOT met, so this routes to /complete (no qualifying), not /fail."""
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

        # Partial failure → not F4. /complete with no qualifying.
        api.fail.assert_not_called()
        api.complete_track.assert_called_once()

    def test_all_sam2_tracks_fail_calls_fail_with_all_scenes_failed(self):
        """Coarse + precise pass produce candidate scenes; SAM2
        tracker raises on every scene. Worker MUST call /fail with
        ``all_scenes_failed``, NOT /complete with empty plan."""
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
        assert kwargs["error_code"] == "all_scenes_failed"
        assert "sam2_track" in kwargs["error_message"]
        api.complete_track.assert_not_called()
