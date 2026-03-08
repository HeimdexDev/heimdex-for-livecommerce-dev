from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import UniqueConstraint

from app.modules.youtube.models import YouTubeChannel, YouTubeVideo
from app.modules.youtube.repository import YouTubeChannelRepository, YouTubeVideoRepository


@pytest.mark.asyncio
async def test_channel_repository_create_update_and_delete_flushes():
    session = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()
    repo = YouTubeChannelRepository(session)

    channel = await repo.create(
        org_id=uuid4(),
        channel_id="UCabc123",
        channel_url="https://www.youtube.com/channel/UCabc123",
        channel_name="test",
    )
    session.flush.assert_awaited_once()

    await repo.update(
        channel,
        channel_name="renamed",
        thumbnail_url="https://img.youtube.com/x.jpg",
        sync_enabled=False,
    )
    await repo.delete(channel)

    assert channel.channel_name == "renamed"
    assert channel.thumbnail_url == "https://img.youtube.com/x.jpg"
    assert channel.sync_enabled is False
    assert session.flush.await_count == 3


@pytest.mark.asyncio
async def test_channel_repository_get_by_id_and_list_queries_are_org_scoped():
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    result.scalars.return_value.all.return_value = []
    session.execute.return_value = result
    repo = YouTubeChannelRepository(session)

    await repo.get_by_id(uuid4(), uuid4())
    await repo.list_by_org(uuid4(), sync_enabled=True)

    stmt_get = str(session.execute.await_args_list[0].args[0])
    stmt_list = str(session.execute.await_args_list[1].args[0])
    assert "youtube_channels.org_id" in stmt_get
    assert "youtube_channels.org_id" in stmt_list


@pytest.mark.asyncio
async def test_channel_repository_updates_last_synced_at_and_count():
    session = AsyncMock()
    repo = YouTubeChannelRepository(session)
    channel = YouTubeChannel(
        org_id=uuid4(),
        channel_id="UCxyz12345",
        channel_url="https://www.youtube.com/channel/UCxyz12345",
        channel_name="channel",
    )

    now = datetime.now(UTC)
    await repo.update_last_synced_at(channel, synced_at=now)
    await repo.set_video_count(channel, -10)

    assert channel.last_synced_at == now
    assert channel.video_count == 0
    assert session.flush.await_count == 2


@pytest.mark.asyncio
async def test_video_repository_create_update_mark_deleted_and_delete_flushes():
    session = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()
    repo = YouTubeVideoRepository(session)
    video = await repo.create(
        org_id=uuid4(),
        channel_id=uuid4(),
        youtube_video_id="abc123xyz89",
        video_id="yt_1234567890abcdef",
        title="Sample",
    )

    await repo.update_status(
        video=video,
        processing_status="complete",
        has_subtitles=True,
        subtitle_language="ko",
        enrichment_status={"subtitle": "complete"},
    )
    await repo.mark_original_deleted(video)
    await repo.delete(video)

    assert video.processing_status == "complete"
    assert video.has_subtitles is True
    assert video.subtitle_language == "ko"
    assert video.original_deleted is True
    assert session.flush.await_count == 4


@pytest.mark.asyncio
async def test_video_repository_list_and_get_queries_are_org_scoped():
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    result.scalars.return_value.all.return_value = []
    result.all.return_value = []
    session.execute.return_value = result
    repo = YouTubeVideoRepository(session)

    await repo.get_by_id(uuid4(), uuid4())
    await repo.get_by_youtube_video_id(uuid4(), "yt-id")
    await repo.list_by_channel(org_id=uuid4(), channel_id=uuid4())
    await repo.list_known_youtube_video_ids(org_id=uuid4(), channel_id=uuid4())

    statements = [str(call.args[0]) for call in session.execute.await_args_list]
    assert all("youtube_videos.org_id" in statement for statement in statements)


@pytest.mark.asyncio
async def test_video_repository_known_video_ids_and_cleanup_candidates():
    complete = SimpleNamespace(enrichment_status={"subtitle": "complete", "ocr": "skipped"})
    pending = SimpleNamespace(enrichment_status={"subtitle": "pending"})
    session = AsyncMock()
    repo = YouTubeVideoRepository(session)

    result_ids = MagicMock()
    result_ids.all.return_value = [("yt001",), ("yt002",)]
    session.execute.return_value = result_ids
    video_ids = await repo.list_known_youtube_video_ids(org_id=uuid4(), channel_id=uuid4())
    assert video_ids == ["yt001", "yt002"]

    result_cleanup = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = [complete, pending]
    result_cleanup.scalars.return_value = scalars
    session.execute.return_value = result_cleanup
    videos = await repo.list_cleanup_candidates(org_id=uuid4())
    assert videos == [complete]


def test_channel_model_has_unique_constraint_for_org_channel_id():
    constraints = [
        item for item in YouTubeChannel.__table_args__ if isinstance(item, UniqueConstraint)
    ]
    names = [constraint.name for constraint in constraints]
    assert "uq_youtube_channels_org_channel" in names


def test_video_model_has_unique_constraint_for_org_youtube_video_id():
    constraints = [
        item for item in YouTubeVideo.__table_args__ if isinstance(item, UniqueConstraint)
    ]
    names = [constraint.name for constraint in constraints]
    assert "uq_youtube_videos_org_yt_id" in names
