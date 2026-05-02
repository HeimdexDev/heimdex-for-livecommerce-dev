"""Phase 3c-B Item 3 tests — render enqueue.

Three layers:
  1. ``_build_composition_spec`` — pure transformation from
     ``StitchPlan`` to a JSON-serialisable dict the api will
     re-validate as ``CompositionSpec``.
  2. ``ApiClient.enqueue_render`` — wire shape going OUT to the api.
  3. ``handle_track_job`` happy path + render-enqueue failure path.
"""

from __future__ import annotations

import io
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from PIL import Image

from heimdex_media_pipelines.product_track.alignment import AnnotatedWindow
from heimdex_media_pipelines.product_track.sam2_pass import (
    BBoxXYWH,
    TrackedSample,
)
from heimdex_media_pipelines.product_track.stitching import StitchPlan
from heimdex_media_pipelines.product_track.subset_selector import ScoredWindow

from src.settings import WorkerSettings
from src.tasks.track import _build_composition_spec, handle_track_job


def _settings() -> WorkerSettings:
    return WorkerSettings(
        product_v2_enabled=True,
        sqs_product_track_queue_url="https://sqs/q",
        drive_internal_api_key="t",
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


def _make_annotated(*, scene_id: str, start_ms: int, end_ms: int) -> AnnotatedWindow:
    return AnnotatedWindow(
        scene_id=scene_id,
        window_start_ms=start_ms,
        window_end_ms=end_ms,
        avg_bbox_area_pct=0.1,
        avg_confidence=0.85,
        peak_confidence=0.9,
        frame_count=20,
        rejected_reason=None,
        has_narration_mention=False,
        has_ocr_overlap=False,
    )


def _make_scored(window: AnnotatedWindow, score: float = 0.8) -> ScoredWindow:
    return ScoredWindow(
        window=window,
        composite_score=score,
        score_components={
            "prominence": 0.3, "narration": 0.0, "ocr": 0.0,
            "duration_fitness": 0.5, "spread_bonus": 0.0,
        },
    )


# =====================================================================
# _build_composition_spec
# =====================================================================


class TestBuildCompositionSpec:
    def test_chronological_hard_cut_back_to_back(self):
        """Each ScoredWindow's source range is preserved verbatim;
        timeline_start_ms is the running cumulative sum so clips
        play back-to-back with no gaps + no transitions."""
        windows = [
            _make_scored(
                _make_annotated(scene_id="s1", start_ms=1000, end_ms=4000),
                score=0.9,
            ),
            _make_scored(
                _make_annotated(scene_id="s2", start_ms=10000, end_ms=15000),
                score=0.7,
            ),
        ]
        plan = StitchPlan(
            windows=windows,
            duration_target_sec=30,
            duration_actual_ms=8000,
            scorer_version="v1.0",
            subset_picker_version="v1.0",
        )

        spec = _build_composition_spec(plan=plan, os_video_id="gd_abc")

        clips = spec["scene_clips"]
        assert len(clips) == 2
        # Clip 1 — source [1000,4000), placed at 0 on the timeline.
        assert clips[0]["scene_id"] == "s1"
        assert clips[0]["video_id"] == "gd_abc"
        assert clips[0]["source_type"] == "gdrive"
        assert clips[0]["start_ms"] == 1000
        assert clips[0]["end_ms"] == 4000
        assert clips[0]["timeline_start_ms"] == 0
        # Clip 2 — source [10000,15000), placed after clip 1's
        # 3000ms duration.
        assert clips[1]["start_ms"] == 10000
        assert clips[1]["end_ms"] == 15000
        assert clips[1]["timeline_start_ms"] == 3000
        # Defaults left to api server-side; spec stays minimal.
        assert "output" not in spec
        assert "subtitles" not in spec
        assert "transitions" not in spec

    def test_validates_against_composition_spec_schema(self):
        """The dict shape MUST satisfy the contracts'
        ``CompositionSpec`` validator — drift here would 422 at the
        api boundary."""
        from heimdex_media_contracts.composition import CompositionSpec

        windows = [
            _make_scored(
                _make_annotated(scene_id="s1", start_ms=0, end_ms=5000),
                score=0.9,
            ),
        ]
        plan = StitchPlan(
            windows=windows,
            duration_target_sec=30,
            duration_actual_ms=5000,
            scorer_version="v1.0",
            subset_picker_version="v1.0",
        )
        spec = _build_composition_spec(plan=plan, os_video_id="gd_xyz")
        # Should not raise.
        validated = CompositionSpec.model_validate(spec)
        assert len(validated.scene_clips) == 1


# =====================================================================
# ApiClient.enqueue_render
# =====================================================================


class TestApiClientEnqueueRender:
    def test_posts_correct_url_and_body_shape(self):
        from src.api_client import ApiClient
        api = ApiClient(base_url="https://api.test", internal_api_key="t")
        fake_http = MagicMock()
        api._client = fake_http  # noqa: SLF001
        scan_job_id = uuid4()
        render_job_id = uuid4()
        ok = MagicMock()
        ok.json.return_value = {"render_job_id": str(render_job_id)}
        ok.raise_for_status = MagicMock()
        fake_http.post.return_value = ok

        out = api.enqueue_render(
            scan_job_id=scan_job_id,
            claimed_by="worker-x",
            video_id="gd_abc",
            title="제품 X",
            composition={"scene_clips": []},
        )
        assert out == render_job_id
        args, kwargs = fake_http.post.call_args
        assert args[0] == (
            f"https://api.test/internal/products/{scan_job_id}/render"
        )
        assert kwargs["json"] == {
            "claimed_by": "worker-x",
            "payload": {
                "video_id": "gd_abc",
                "title": "제품 X",
                "composition": {"scene_clips": []},
            },
        }


# =====================================================================
# handle_track_job — happy path through render enqueue
# =====================================================================


class TestHandleTrackJobRenderEnqueue:
    def _make_api(self, *, render_job_id):
        api = MagicMock()
        api.fetch_scenes_with_keyframes.return_value = _scenes_response(n=3)
        api.find_similar_scenes.return_value = [
            {"scene_id": f"gd_test_scene_{i:03d}", "similarity": 0.9}
            for i in range(3)
        ]
        api.fetch_scenes_content.return_value = []
        api.enqueue_render.return_value = render_job_id
        return api

    def _make_full_pipeline_mocks(self):
        canonical_vec = [1.0] + [0.0] * 767
        embedder = MagicMock()
        embedder.embed.return_value = canonical_vec
        good_buf = io.BytesIO()
        Image.new("RGB", (4, 4), 0).save(good_buf, format="JPEG")
        s3 = MagicMock()
        s3.get_object_bytes.return_value = good_buf.getvalue()
        # SAM2 returns a dense, high-confidence sample stream so
        # window-assembly produces an accepted window.
        tracker = MagicMock()
        def _good_track(*, scene_id, **_kwargs):
            return [
                TrackedSample(
                    frame_timestamp_ms=ts,
                    bbox=BBoxXYWH(x=10, y=10, width=200, height=200),
                    mask_confidence=0.9,
                    frame_width=1280,
                    frame_height=720,
                )
                for ts in range(0, 4000, 200)  # 2s span @ 5fps
            ]
        tracker.track.side_effect = _good_track
        # GreedyPicker behaves deterministically without an OpenAI
        # client — use an empty key in settings so
        # ``_build_picker`` falls back to it.
        return embedder, s3, tracker

    def test_happy_path_calls_enqueue_render_and_complete_with_id(self):
        render_job_id = uuid4()
        api = self._make_api(render_job_id=render_job_id)
        embedder, s3, tracker = self._make_full_pipeline_mocks()

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

        # Render was enqueued with the video_id from scenes-with-keyframes.
        api.enqueue_render.assert_called_once()
        kwargs = api.enqueue_render.call_args.kwargs
        assert kwargs["video_id"] == "gd_test"
        assert kwargs["claimed_by"] == "test-worker"
        # Title defaults to the llm_label.
        assert kwargs["title"] == "테스트 제품"
        # Composition shape: at least one clip, video_id propagated.
        assert isinstance(kwargs["composition"], dict)
        assert len(kwargs["composition"]["scene_clips"]) >= 1
        assert kwargs["composition"]["scene_clips"][0]["video_id"] == "gd_test"

        # /complete called with the api-returned render_job_id.
        api.complete_track.assert_called_once()
        complete_kwargs = api.complete_track.call_args.kwargs
        assert complete_kwargs["render_job_id"] == render_job_id

    def test_render_enqueue_failure_routes_to_fail_render_enqueue_failed(self):
        """If the api refuses the render (5xx, validation error,
        rate-limit, budget cap), worker MUST /fail with the api's
        dedicated ``render_enqueue_failed`` enum literal — NOT
        internal_error. The user-facing UI distinguishes "the
        tracker worked but the render didn't kick off" from
        generic worker bugs."""
        api = self._make_api(render_job_id=uuid4())
        request = httpx.Request("POST", "http://api/internal/products/x/render")
        api.enqueue_render.side_effect = httpx.HTTPStatusError(
            "503 Service Unavailable",
            request=request,
            response=httpx.Response(503, request=request),
        )
        embedder, s3, tracker = self._make_full_pipeline_mocks()

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

        api.complete_track.assert_not_called()
        api.fail.assert_called_once()
        fail_kwargs = api.fail.call_args.kwargs
        assert fail_kwargs["error_code"] == "render_enqueue_failed"
        assert "503" in fail_kwargs["error_message"]
