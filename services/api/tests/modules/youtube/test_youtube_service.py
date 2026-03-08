from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.youtube.schemas import CreateYouTubeVideoRequest
from app.modules.youtube.models import YouTubeChannel, YouTubeVideo
from app.modules.youtube.service import REFERENCE_LIBRARY_NAME, YouTubeService


def _make_service():
    return YouTubeService(
        channel_repo=MagicMock(),
        video_repo=MagicMock(),
        library_repo=MagicMock(),
    )


@pytest.mark.asyncio
async def test_get_or_create_reference_library_returns_existing():
    org_id = uuid4()
    existing = SimpleNamespace(id=uuid4(), name=REFERENCE_LIBRARY_NAME)
    service = _make_service()
    service.library_repo.get_by_name = AsyncMock(return_value=existing)
    service.library_repo.create = AsyncMock()

    result = await service.get_or_create_reference_library(org_id)

    assert result is existing
    service.library_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_or_create_reference_library_creates_when_missing():
    org_id = uuid4()
    created = SimpleNamespace(id=uuid4(), name=REFERENCE_LIBRARY_NAME)
    service = _make_service()
    service.library_repo.get_by_name = AsyncMock(return_value=None)
    service.library_repo.create = AsyncMock(return_value=created)

    result = await service.get_or_create_reference_library(org_id)

    assert result is created
    service.library_repo.create.assert_awaited_once_with(org_id=org_id, name=REFERENCE_LIBRARY_NAME)


def test_resolve_channel_identity_with_channel_url():
    service = _make_service()
    channel_id, channel_name = service.resolve_channel_identity(
        "https://www.youtube.com/channel/UCabcdEFGH123456",
        None,
    )
    assert channel_id == "UCabcdEFGH123456"
    assert channel_name == "UCabcdEFGH123456"


def test_resolve_channel_identity_with_direct_channel_id():
    service = _make_service()
    channel_id, channel_name = service.resolve_channel_identity("UCabcdefgh1234", "name")
    assert channel_id == "UCabcdefgh1234"
    assert channel_name == "name"


def test_resolve_channel_identity_with_handle_url():
    service = _make_service()
    channel_id, channel_name = service.resolve_channel_identity(
        "https://www.youtube.com/@heimdex",
        None,
    )
    assert channel_id.startswith("UC")
    assert len(channel_id) == 24
    assert channel_name == "@heimdex"


def test_resolve_channel_identity_invalid_url_raises():
    service = _make_service()
    with pytest.raises(ValueError):
        service.resolve_channel_identity("https://example.com/channel/test", None)


def test_inject_subtitle_status_sets_complete():
    service = _make_service()
    video = YouTubeVideo(
        org_id=uuid4(),
        channel_id=uuid4(),
        youtube_video_id="abc123xyz89",
        video_id="yt_1234567890abcdef",
        title="sample",
        subtitle_language=None,
        has_subtitles=False,
        enrichment_status={"ocr": "complete"},
    )

    service.inject_subtitle_status(
        video=video,
        subtitle_language="ko",
        has_subtitles=True,
    )

    assert video.subtitle_language == "ko"
    assert video.has_subtitles is True
    assert video.enrichment_status["subtitle"] == "complete"


def test_inject_subtitle_status_marks_skipped_when_missing():
    service = _make_service()
    video = YouTubeVideo(
        org_id=uuid4(),
        channel_id=uuid4(),
        youtube_video_id="abc123xyz89",
        video_id="yt_1234567890abcdef",
        title="sample",
        subtitle_language="ko",
        has_subtitles=True,
        enrichment_status={"subtitle": "complete"},
    )

    service.inject_subtitle_status(
        video=video,
        subtitle_language=None,
        has_subtitles=False,
    )

    assert video.subtitle_language is None
    assert video.has_subtitles is False
    assert video.enrichment_status["subtitle"] == "skipped"


@pytest.mark.asyncio
async def test_create_video_record_updates_channel_count():
    service = _make_service()
    org_id = uuid4()
    channel = YouTubeChannel(
        org_id=org_id,
        channel_id="UCabc1234567",
        channel_url="https://www.youtube.com/channel/UCabc1234567",
        channel_name="channel",
        video_count=2,
    )
    request = CreateYouTubeVideoRequest(youtube_video_id="abc123xyz89", title="Sample")
    video = SimpleNamespace(id=uuid4(), youtube_video_id=request.youtube_video_id)
    service.video_repo.get_by_youtube_video_id = AsyncMock(return_value=None)
    service.video_repo.create = AsyncMock(return_value=video)

    created = await service.create_video_record(org_id=org_id, channel=channel, request=request)

    assert created is video
    assert channel.video_count == 3
