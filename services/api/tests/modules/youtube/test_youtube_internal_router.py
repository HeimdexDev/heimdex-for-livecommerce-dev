from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.dependencies import verify_internal_token
from app.modules.libraries.repository import LibraryRepository
from app.modules.youtube.internal_router import (
    create_video,
    list_cleanup_candidates,
    list_enabled_channels,
    list_known_video_ids,
    mark_original_deleted,
    update_video_status,
)
from app.modules.youtube.repository import YouTubeChannelRepository, YouTubeVideoRepository
from app.modules.youtube.schemas import CreateYouTubeVideoRequest, UpdateYouTubeVideoStatusRequest


def _channel(org_id, channel_pk=None):
    return SimpleNamespace(
        id=channel_pk or uuid4(),
        org_id=org_id,
        channel_id="UCabc1234567",
        channel_url="https://youtube.com/channel/UCabc1234567",
        channel_name="Channel",
        thumbnail_url=None,
        video_count=0,
        last_synced_at=None,
        sync_enabled=True,
        created_at=datetime.now(UTC),
    )


def _video(org_id, channel_pk, video_pk=None):
    return SimpleNamespace(
        id=video_pk or uuid4(),
        org_id=org_id,
        channel_id=channel_pk,
        youtube_video_id="abc123xyz89",
        video_id="yt_1234567890abcdef",
        title="video",
        duration_seconds=120,
        publish_date=None,
        subtitle_language=None,
        processing_status="pending",
        has_subtitles=False,
        enrichment_status={"subtitle": "pending"},
        original_deleted=False,
        created_at=datetime.now(UTC),
    )


class TestInternalAuth:
    @pytest.mark.asyncio
    async def test_verify_internal_token_accepts_valid_bearer(self):
        from unittest.mock import patch

        with patch("app.dependencies.get_settings") as mock_settings:
            mock_settings.return_value.drive_internal_api_key = "secret-key"
            token = await verify_internal_token("Bearer secret-key")
        assert token == "secret-key"

    @pytest.mark.asyncio
    async def test_verify_internal_token_rejects_invalid_bearer(self):
        from unittest.mock import patch

        with patch("app.dependencies.get_settings") as mock_settings:
            mock_settings.return_value.drive_internal_api_key = "secret-key"
            with pytest.raises(HTTPException) as exc_info:
                await verify_internal_token("Bearer wrong")
        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_list_enabled_channels_and_known_video_ids():
    org_id = uuid4()
    channel = _channel(org_id)

    channel_repo = cast(YouTubeChannelRepository, AsyncMock())
    channel_repo.list_by_org = AsyncMock(return_value=[channel])
    channel_repo.get_by_id = AsyncMock(return_value=channel)

    video_repo = cast(YouTubeVideoRepository, AsyncMock())
    video_repo.list_known_youtube_video_ids = AsyncMock(return_value=["abc123xyz89"])

    channels_res = await list_enabled_channels(str(org_id), "token", channel_repo)
    assert channels_res.total == 1

    ids_res = await list_known_video_ids(channel.id, str(org_id), "token", channel_repo, video_repo)
    assert ids_res.total == 1
    assert ids_res.video_ids == ["abc123xyz89"]


@pytest.mark.asyncio
async def test_create_video_update_status_cleanup_and_mark_deleted():
    org_id = uuid4()
    channel = _channel(org_id)
    video = _video(org_id, channel.id)

    channel_repo = cast(YouTubeChannelRepository, AsyncMock())
    channel_repo.get_by_id = AsyncMock(return_value=channel)
    channel_repo.set_video_count = AsyncMock(return_value=channel)

    video_repo = cast(YouTubeVideoRepository, AsyncMock())
    video_repo.get_by_youtube_video_id = AsyncMock(return_value=None)
    video_repo.create = AsyncMock(return_value=video)
    video_repo.get_by_id = AsyncMock(return_value=video)
    video_repo.update_status = AsyncMock(return_value=video)
    video_repo.list_cleanup_candidates = AsyncMock(return_value=[video])
    video_repo.mark_original_deleted = AsyncMock(return_value=video)

    library_repo = cast(LibraryRepository, AsyncMock())
    library_repo.get_by_name = AsyncMock(return_value=SimpleNamespace(id=uuid4()))

    create_req = CreateYouTubeVideoRequest(youtube_video_id="abc123xyz89", title="Sample")
    created = await create_video(
        channel.id,
        create_req,
        str(org_id),
        "token",
        channel_repo,
        video_repo,
        library_repo,
    )
    assert created.youtube_video_id == "abc123xyz89"

    status_req = UpdateYouTubeVideoStatusRequest(
        processing_status="complete",
        subtitle_language="ko",
        has_subtitles=True,
    )
    updated = await update_video_status(
        video.id,
        status_req,
        str(org_id),
        "token",
        video_repo,
        channel_repo,
        library_repo,
    )
    assert updated.processing_status == "complete"
    assert updated.has_subtitles is True

    cleanup = await list_cleanup_candidates(str(org_id), "token", video_repo)
    assert cleanup.total == 1

    marked = await mark_original_deleted(video.id, str(org_id), "token", video_repo)
    assert marked.id == video.id


@pytest.mark.asyncio
async def test_internal_endpoints_404_and_bad_org_header():
    org_id = uuid4()
    channel_repo = cast(YouTubeChannelRepository, AsyncMock())
    video_repo = cast(YouTubeVideoRepository, AsyncMock())
    channel_repo.get_by_id = AsyncMock(return_value=None)
    video_repo.get_by_id = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as bad_org:
        await list_enabled_channels("not-a-uuid", "token", channel_repo)
    assert bad_org.value.status_code == 400

    with pytest.raises(HTTPException) as channel_missing:
        await list_known_video_ids(uuid4(), str(org_id), "token", channel_repo, video_repo)
    assert channel_missing.value.status_code == 404

    with pytest.raises(HTTPException) as video_missing:
        await mark_original_deleted(uuid4(), str(org_id), "token", video_repo)
    assert video_missing.value.status_code == 404
