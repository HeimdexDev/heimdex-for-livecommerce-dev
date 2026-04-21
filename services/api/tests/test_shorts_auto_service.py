"""Service orchestration tests with all deps mocked.

Verifies:
- 404 when video doesn't exist
- video_too_short when proxy_duration_ms below floor
- empty result when no candidate scenes match mode filter
- successful both-mode end-to-end with synthetic scenes
- product mode hard-filters scenes with people via the contracts scorer
- auto_render delegates to ShortsRenderService.create_render_job
- auto_caption=True returns 422 (P4 deferred)
- insufficient clips → 422 from auto_render
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.shorts_auto.schemas import (
    AutoRenderRequest,
    AutoSelectRequest,
    ScoringModeRequest,
)
from app.modules.shorts_auto.service import ShortsAutoService
from heimdex_media_contracts.scenes.schemas import SceneDocument


def _scene(
    scene_id: str,
    *,
    video_id: str = "vid",
    index: int = 0,
    start_ms: int = 0,
    end_ms: int = 35_000,
    people: list[str] | None = None,
    product_tags: list[str] | None = None,
    keyword_tags: list[str] | None = None,
    transcript_char_count: int = 100,
) -> SceneDocument:
    return SceneDocument(
        scene_id=scene_id,
        video_id=video_id,
        index=index,
        start_ms=start_ms,
        end_ms=end_ms,
        keyframe_timestamp_ms=(start_ms + end_ms) // 2,
        people_cluster_ids=people or [],
        product_tags=product_tags or [],
        keyword_tags=keyword_tags or [],
        transcript_char_count=transcript_char_count,
    )


def _make_service(
    *,
    selector_scenes: list[SceneDocument] | None = None,
    drive_file=None,
    render_response=None,
):
    selector = MagicMock()
    selector.fetch_candidates = AsyncMock(return_value=selector_scenes or [])

    drive_file_repo = MagicMock()
    drive_file_repo.get_by_video_id = AsyncMock(return_value=drive_file)

    shorts_render_service = MagicMock()
    shorts_render_service.create_render_job = AsyncMock(return_value=render_response)

    svc = ShortsAutoService(
        selector=selector,
        drive_file_repo=drive_file_repo,
        shorts_render_service=shorts_render_service,
    )
    return svc, selector, drive_file_repo, shorts_render_service


def _drive_file(duration_ms: int = 600_000):
    """Mock drive file. proxy_duration_ms=600000 = 10min, well above default 5min floor."""
    return SimpleNamespace(video_id="vid", proxy_duration_ms=duration_ms)


def _render_response():
    return SimpleNamespace(
        id=uuid4(),
        video_id="vid",
        title="Auto both (5 clips)",
        status="queued",
        created_at=datetime.now(timezone.utc),
        completed_at=None,
        render_time_ms=None,
        output_duration_ms=None,
        output_size_bytes=None,
        error=None,
    )


@pytest.mark.asyncio
class TestAutoSelect:
    async def test_404_when_video_not_found(self):
        svc, *_ = _make_service(drive_file=None)
        with pytest.raises(HTTPException) as exc:
            await svc.auto_select(
                org_id=uuid4(),
                user_id=uuid4(),
                req=AutoSelectRequest(video_id="missing", mode=ScoringModeRequest.BOTH),
            )
        assert exc.value.status_code == 404

    async def test_video_too_short_returns_skipped_reason(self):
        svc, *_ = _make_service(drive_file=_drive_file(duration_ms=60_000))
        resp = await svc.auto_select(
            org_id=uuid4(),
            user_id=uuid4(),
            req=AutoSelectRequest(video_id="vid", mode=ScoringModeRequest.BOTH),
        )
        assert resp.clips == []
        assert resp.skipped_reason == "video_too_short"

    async def test_unknown_proxy_duration_logs_and_proceeds(self, caplog):
        """If proxy_duration_ms is None (transcode pending), we do NOT
        treat it as video_too_short. Proceeds — scene corpus check below
        catches empty-corpus cases cleanly."""
        # drive_file with no duration set; selector returns empty scenes
        svc, *_ = _make_service(
            drive_file=_drive_file(duration_ms=0),  # → None-equivalent
            selector_scenes=[],
        )
        # drive_file with proxy_duration_ms=None
        svc.drive_file_repo.get_by_video_id = AsyncMock(
            return_value=SimpleNamespace(video_id="vid", proxy_duration_ms=None)
        )
        resp = await svc.auto_select(
            org_id=uuid4(),
            user_id=uuid4(),
            req=AutoSelectRequest(video_id="vid", mode=ScoringModeRequest.BOTH),
        )
        # NOT rejected as too short — propagates to scene-level empty check.
        assert resp.skipped_reason == "no_candidate_scenes_after_filter"

    async def test_no_candidates_returns_skipped_reason(self):
        svc, *_ = _make_service(
            drive_file=_drive_file(),
            selector_scenes=[],
        )
        resp = await svc.auto_select(
            org_id=uuid4(),
            user_id=uuid4(),
            req=AutoSelectRequest(video_id="vid", mode=ScoringModeRequest.BOTH),
        )
        assert resp.clips == []
        assert resp.skipped_reason == "no_candidate_scenes_after_filter"

    async def test_both_mode_returns_clips_for_eligible_scenes(self):
        scenes = [
            _scene(
                f"vid_scene_{i:03d}",
                index=i,
                start_ms=i * 35_000,
                end_ms=(i + 1) * 35_000 - 5_000,
                keyword_tags=["cta"],
                product_tags=["스킨케어"],
            )
            for i in range(8)
        ]
        svc, *_ = _make_service(drive_file=_drive_file(), selector_scenes=scenes)
        resp = await svc.auto_select(
            org_id=uuid4(),
            user_id=uuid4(),
            req=AutoSelectRequest(
                video_id="vid",
                mode=ScoringModeRequest.BOTH,
                count=3,
                prefer_continuous=False,
            ),
        )
        assert resp.skipped_reason is None
        assert 1 <= len(resp.clips) <= 3
        # Chronologically sorted
        starts = [c.start_ms for c in resp.clips]
        assert starts == sorted(starts)

    async def test_product_mode_hard_filters_scenes_with_people(self):
        # Mix: scenes 0,1,4,5 are person-free + have product; 2,3 have people.
        scenes = []
        for i in range(8):
            people = ["p1"] if i in (2, 3, 6, 7) else []
            scenes.append(
                _scene(
                    f"vid_scene_{i:03d}",
                    index=i,
                    start_ms=i * 35_000,
                    end_ms=(i + 1) * 35_000 - 5_000,
                    people=people,
                    product_tags=["스킨케어"] if i in (0, 1, 4, 5) else [],
                    keyword_tags=["product_demo"] if i in (0, 1, 4, 5) else [],
                )
            )
        svc, *_ = _make_service(drive_file=_drive_file(), selector_scenes=scenes)
        resp = await svc.auto_select(
            org_id=uuid4(),
            user_id=uuid4(),
            req=AutoSelectRequest(
                video_id="vid",
                mode=ScoringModeRequest.PRODUCT,
                count=2,
                prefer_continuous=False,
            ),
        )
        assert resp.skipped_reason is None
        assert len(resp.clips) >= 1
        # No emitted clip references an ineligible scene
        ineligible = {"vid_scene_002", "vid_scene_003", "vid_scene_006", "vid_scene_007"}
        for c in resp.clips:
            assert not (set(c.scene_ids) & ineligible)


@pytest.mark.asyncio
class TestAutoRender:
    async def test_auto_caption_true_rejected_with_422(self):
        svc, *_ = _make_service(drive_file=_drive_file())
        with pytest.raises(HTTPException) as exc:
            await svc.auto_render(
                org_id=uuid4(),
                user_id=uuid4(),
                req=AutoRenderRequest(
                    video_id="vid",
                    mode=ScoringModeRequest.BOTH,
                    auto_caption=True,
                ),
            )
        assert exc.value.status_code == 422
        assert "auto_caption" in exc.value.detail

    async def test_insufficient_clips_returns_422(self):
        scenes = [
            _scene(
                "vid_scene_000",
                start_ms=0,
                end_ms=35_000,
                keyword_tags=["cta"],
            )
        ]
        svc, *_ = _make_service(drive_file=_drive_file(), selector_scenes=scenes)
        with pytest.raises(HTTPException) as exc:
            await svc.auto_render(
                org_id=uuid4(),
                user_id=uuid4(),
                req=AutoRenderRequest(
                    video_id="vid",
                    mode=ScoringModeRequest.BOTH,
                    count=5,
                ),
            )
        assert exc.value.status_code == 422
        assert "insufficient" in exc.value.detail

    async def test_successful_render_delegates_to_shorts_render(self):
        scenes = [
            _scene(
                f"vid_scene_{i:03d}",
                index=i,
                start_ms=i * 35_000,
                end_ms=(i + 1) * 35_000 - 5_000,
                keyword_tags=["cta", "product_demo"],
                product_tags=["스킨케어"],
            )
            for i in range(8)
        ]
        render_resp = _render_response()
        svc, _, _, render_service = _make_service(
            drive_file=_drive_file(),
            selector_scenes=scenes,
            render_response=render_resp,
        )
        result = await svc.auto_render(
            org_id=uuid4(),
            user_id=uuid4(),
            req=AutoRenderRequest(
                video_id="vid",
                mode=ScoringModeRequest.BOTH,
                count=2,
                prefer_continuous=False,
            ),
        )
        assert result is render_resp
        # Delegation happened exactly once
        render_service.create_render_job.assert_awaited_once()
        # Payload includes a CompositionSpec with the right video_id
        call = render_service.create_render_job.await_args
        payload = call.kwargs["payload"]
        assert payload.video_id == "vid"
        assert payload.composition.scene_clips
        for clip in payload.composition.scene_clips:
            assert clip.video_id == "vid"
            assert clip.source_type == "gdrive"

    async def test_composition_emits_per_scene_clips_that_would_pass_render_validation(self):
        """Regression: each SceneClipSpec's source span must sit inside
        its NAMED scene's boundaries so ShortsRenderService._validate_scene_clips
        passes. Previously the service emitted one SceneClipSpec per AutoClip
        attached to the first member's scene_id with the whole clip's span,
        which breaks validation for multi-scene continuous clips."""
        # 3 back-to-back scenes forming one 30s continuous clip (each 10s).
        scenes = [
            _scene(
                f"vid_scene_{i:03d}",
                index=i,
                start_ms=i * 10_000,
                end_ms=(i + 1) * 10_000,
                keyword_tags=["cta", "product_demo"],
                product_tags=["스킨케어"],
                transcript_char_count=100,
            )
            for i in range(3)
        ]
        render_resp = _render_response()
        svc, _, _, render_service = _make_service(
            drive_file=_drive_file(),
            selector_scenes=scenes,
            render_response=render_resp,
        )
        await svc.auto_render(
            org_id=uuid4(),
            user_id=uuid4(),
            req=AutoRenderRequest(
                video_id="vid",
                mode=ScoringModeRequest.BOTH,
                count=1,
                target_duration_sec=30,
                min_duration_sec=30,
            ),
        )
        payload = render_service.create_render_job.await_args.kwargs["payload"]
        # Should emit 3 SceneClipSpecs (one per scene), not 1 covering all three.
        assert len(payload.composition.scene_clips) == 3
        # Each SceneClipSpec's span must fit inside its named scene (mirrors
        # _validate_scene_clips in ShortsRenderService).
        scene_bounds = {s.scene_id: (s.start_ms, s.end_ms) for s in scenes}
        for spec in payload.composition.scene_clips:
            lo, hi = scene_bounds[spec.scene_id]
            assert lo <= spec.start_ms < spec.end_ms <= hi, (
                f"{spec.scene_id}: clip [{spec.start_ms},{spec.end_ms}] "
                f"must lie within scene [{lo},{hi}]"
            )
        # Timeline is packed back-to-back.
        timeline_sorted = sorted(
            payload.composition.scene_clips, key=lambda c: c.timeline_start_ms
        )
        for i in range(len(timeline_sorted) - 1):
            assert (
                timeline_sorted[i].timeline_start_ms + timeline_sorted[i].duration_ms
                == timeline_sorted[i + 1].timeline_start_ms
            )

    async def test_composition_truncates_to_respect_5_minute_cap(self):
        """CompositionSpec caps total at 300s. We trim the trailing member
        so validation doesn't raise."""
        # 6 × 60s scenes: total 360s before cap.
        scenes = [
            _scene(
                f"vid_scene_{i:03d}",
                index=i,
                start_ms=i * 60_000,
                end_ms=(i + 1) * 60_000,
                keyword_tags=["cta"],
                product_tags=["스킨케어"],
                transcript_char_count=100,
            )
            for i in range(6)
        ]
        render_resp = _render_response()
        svc, _, _, render_service = _make_service(
            drive_file=_drive_file(duration_ms=600_000),
            selector_scenes=scenes,
            render_response=render_resp,
        )
        await svc.auto_render(
            org_id=uuid4(),
            user_id=uuid4(),
            req=AutoRenderRequest(
                video_id="vid",
                mode=ScoringModeRequest.BOTH,
                count=5,
                target_duration_sec=60,
                min_duration_sec=30,
            ),
        )
        payload = render_service.create_render_job.await_args.kwargs["payload"]
        total_timeline = payload.composition.total_duration_ms
        assert total_timeline <= 5 * 60 * 1000, (
            f"composition exceeds 5-min cap: {total_timeline}ms"
        )
