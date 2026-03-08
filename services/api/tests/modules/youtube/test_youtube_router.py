from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.libraries.repository import LibraryRepository
from app.modules.tenancy.context import OrgContext
from app.modules.users.models import User
from app.modules.youtube.repository import YouTubeChannelRepository, YouTubeVideoRepository
from app.modules.youtube.router import (
    delete_channel,
    get_channel,
    list_channel_videos,
    list_channels,
    register_channel,
    trigger_manual_sync,
)
from app.modules.youtube.schemas import RegisterChannelRequest


def _channel(org_id, channel_id=None):
    return SimpleNamespace(
        id=channel_id or uuid4(),
        org_id=org_id,
        channel_id="UCabc1234567",
        channel_url="https://www.youtube.com/channel/UCabc1234567",
        channel_name="Channel",
        thumbnail_url=None,
        video_count=0,
        last_synced_at=None,
        sync_enabled=True,
        created_at=datetime.now(UTC),
    )


def _video(org_id, channel_pk):
    return SimpleNamespace(
        id=uuid4(),
        org_id=org_id,
        channel_id=channel_pk,
        youtube_video_id="abc123xyz89",
        video_id="yt_1234567890abcdef",
        title="video",
        duration_seconds=120,
        publish_date=datetime.now(UTC),
        processing_status="pending",
        has_subtitles=False,
        enrichment_status={"subtitle": "pending"},
        created_at=datetime.now(UTC),
    )


def _ctx() -> OrgContext:
    return OrgContext(org_id=uuid4(), org_slug="testorg")


def _user() -> User:
    return cast(User, cast(object, SimpleNamespace(id=uuid4())))


@pytest.mark.asyncio
async def test_register_channel_success():
    org_ctx = _ctx()
    req = RegisterChannelRequest(channel_url="https://www.youtube.com/channel/UCabc1234567")

    channel_repo = cast(YouTubeChannelRepository, AsyncMock())
    channel_repo.get_by_channel_id = AsyncMock(return_value=None)
    channel_repo.create = AsyncMock(return_value=_channel(org_ctx.org_id))

    video_repo = cast(YouTubeVideoRepository, AsyncMock())

    library_repo = cast(LibraryRepository, AsyncMock())
    library_repo.get_by_name = AsyncMock(return_value=None)
    library_repo.create = AsyncMock(return_value=SimpleNamespace(id=uuid4()))

    res = await register_channel(req, org_ctx, _user(), channel_repo, video_repo, library_repo)

    assert res.channel_id == "UCabc1234567"
    assert res.channel_name == "UCabc1234567"


@pytest.mark.asyncio
async def test_register_channel_invalid_url_returns_422():
    org_ctx = _ctx()
    req = RegisterChannelRequest(channel_url="https://example.com/nope")

    channel_repo = cast(YouTubeChannelRepository, AsyncMock())
    video_repo = cast(YouTubeVideoRepository, AsyncMock())
    library_repo = cast(LibraryRepository, AsyncMock())
    library_repo.get_by_name = AsyncMock(return_value=SimpleNamespace(id=uuid4()))

    with pytest.raises(HTTPException) as exc_info:
        await register_channel(req, org_ctx, _user(), channel_repo, video_repo, library_repo)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_list_get_delete_channels_and_list_videos():
    org_ctx = _ctx()
    channel = _channel(org_ctx.org_id)
    video = _video(org_ctx.org_id, channel.id)

    channel_repo = cast(YouTubeChannelRepository, AsyncMock())
    channel_repo.list_by_org = AsyncMock(return_value=[channel])
    channel_repo.get_by_id = AsyncMock(return_value=channel)
    channel_repo.delete = AsyncMock()

    video_repo = cast(YouTubeVideoRepository, AsyncMock())
    video_repo.list_by_channel = AsyncMock(return_value=[video])

    listed = await list_channels(org_ctx, _user(), channel_repo)
    assert listed.total == 1

    got = await get_channel(channel.id, org_ctx, _user(), channel_repo)
    assert got.id == channel.id

    vids = await list_channel_videos(channel.id, org_ctx, _user(), channel_repo, video_repo)
    assert vids.total == 1
    assert vids.videos[0].youtube_video_id == "abc123xyz89"

    deleted = await delete_channel(channel.id, org_ctx, _user(), channel_repo)
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_channel_not_found_returns_404_on_get_delete_and_sync():
    org_ctx = _ctx()
    channel_id = uuid4()
    channel_repo = cast(YouTubeChannelRepository, AsyncMock())
    channel_repo.get_by_id = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as get_exc:
        await get_channel(channel_id, org_ctx, _user(), channel_repo)
    assert get_exc.value.status_code == 404

    with pytest.raises(HTTPException) as del_exc:
        await delete_channel(channel_id, org_ctx, _user(), channel_repo)
    assert del_exc.value.status_code == 404

    with pytest.raises(HTTPException) as sync_exc:
        await trigger_manual_sync(channel_id, org_ctx, _user(), channel_repo)
    assert sync_exc.value.status_code == 404


@pytest.mark.asyncio
async def test_trigger_manual_sync_accepts_when_channel_exists():
    org_ctx = _ctx()
    channel_id = uuid4()
    channel_repo = cast(YouTubeChannelRepository, AsyncMock())
    channel_repo.get_by_id = AsyncMock(return_value=_channel(org_ctx.org_id, channel_id))

    response = await trigger_manual_sync(channel_id, org_ctx, _user(), channel_repo)

    assert response.status == "accepted"
