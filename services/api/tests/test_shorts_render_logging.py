"""Tests for render event logging in the API service layer."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.shorts_render.service import ShortsRenderService


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    job = SimpleNamespace(
        id=uuid4(), org_id=uuid4(), user_id=uuid4(),
        video_id="gd_vid1", title="Test", status="queued",
        input_spec={}, output_s3_key=None, output_duration_ms=None,
        output_size_bytes=None, render_time_ms=None, error=None,
        created_at=datetime.now(timezone.utc), completed_at=None,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        updated_at=datetime.now(timezone.utc),
    )
    repo.create = AsyncMock(return_value=job)
    return repo, job


@pytest.fixture
def mock_scene_search():
    ss = MagicMock()
    ss.mget_scenes = AsyncMock(return_value={})
    return ss


def _make_payload(scene_id: str, subtitle_count: int = 0):
    from heimdex_media_contracts.composition import CompositionSpec, SceneClipSpec, SubtitleSpec
    from app.modules.shorts_render.schemas import RenderJobCreate

    subtitles = [
        SubtitleSpec(text=f"자막{i}", start_ms=i * 2000, end_ms=(i + 1) * 2000)
        for i in range(subtitle_count)
    ]
    return RenderJobCreate(
        video_id="gd_vid1",
        composition=CompositionSpec(
            scene_clips=[SceneClipSpec(
                scene_id=scene_id, video_id="gd_vid1",
                start_ms=0, end_ms=5000, timeline_start_ms=0,
            )],
            subtitles=subtitles,
        ),
    )


class TestRenderJobCreatedLog:
    @pytest.mark.asyncio
    async def test_create_emits_render_job_created(self, mock_repo, mock_scene_search, capsys) -> None:
        repo, job = mock_repo
        org_id = uuid4()
        scene_id = "scene_001"
        mock_scene_search.mget_scenes = AsyncMock(return_value={
            f"{org_id}:{scene_id}": {"start_ms": 0, "end_ms": 100000},
        })
        svc = ShortsRenderService(repo, mock_scene_search)

        with patch("app.modules.shorts_render.service.get_settings") as ms, \
             patch("app.modules.shorts_render.service.publish_shorts_render_job", create=True):
            ms.return_value = MagicMock(shorts_render_expiry_days=7)
            await svc.create_render_job(org_id, uuid4(), _make_payload(scene_id))

        captured = capsys.readouterr().out
        assert "render_job_created" in captured

    @pytest.mark.asyncio
    async def test_log_contains_job_id_org_id_user_id_video_id(self, mock_repo, mock_scene_search, capsys) -> None:
        repo, job = mock_repo
        org_id = uuid4()
        user_id = uuid4()
        scene_id = "scene_001"
        mock_scene_search.mget_scenes = AsyncMock(return_value={
            f"{org_id}:{scene_id}": {"start_ms": 0, "end_ms": 100000},
        })
        svc = ShortsRenderService(repo, mock_scene_search)

        with patch("app.modules.shorts_render.service.get_settings") as ms, \
             patch("app.modules.shorts_render.service.publish_shorts_render_job", create=True):
            ms.return_value = MagicMock(shorts_render_expiry_days=7)
            await svc.create_render_job(org_id, user_id, _make_payload(scene_id))

        captured = capsys.readouterr().out
        assert str(job.id) in captured
        assert str(org_id) in captured
        assert str(user_id) in captured
        assert "gd_vid1" in captured

    @pytest.mark.asyncio
    async def test_log_contains_clip_and_subtitle_count(self, mock_repo, mock_scene_search, capsys) -> None:
        repo, job = mock_repo
        org_id = uuid4()
        scene_id = "scene_001"
        mock_scene_search.mget_scenes = AsyncMock(return_value={
            f"{org_id}:{scene_id}": {"start_ms": 0, "end_ms": 100000},
        })
        svc = ShortsRenderService(repo, mock_scene_search)

        with patch("app.modules.shorts_render.service.get_settings") as ms, \
             patch("app.modules.shorts_render.service.publish_shorts_render_job", create=True):
            ms.return_value = MagicMock(shorts_render_expiry_days=7)
            await svc.create_render_job(org_id, uuid4(), _make_payload(scene_id, subtitle_count=2))

        captured = capsys.readouterr().out
        assert "clip_count=1" in captured
        assert "subtitle_count=2" in captured
