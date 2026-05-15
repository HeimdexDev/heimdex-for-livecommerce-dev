import hashlib
import re
from typing import cast
from uuid import UUID

from app.logging_config import get_logger
from app.modules.libraries.models import Library
from app.modules.libraries.repository import LibraryRepository

from .models import YouTubeChannel, YouTubeVideo
from .repository import YouTubeChannelRepository, YouTubeVideoRepository
from .schemas import CreateYouTubeVideoRequest

logger = get_logger(__name__)

REFERENCE_LIBRARY_NAME = "유튜브 레퍼런스"

_CHANNEL_ID_RE = re.compile(r"^(UC[a-zA-Z0-9_-]{6,})$")
_CHANNEL_URL_RE = re.compile(r"(?:youtube\.com|youtu\.be)")


class YouTubeService:
    def __init__(
        self,
        channel_repo: YouTubeChannelRepository,
        video_repo: YouTubeVideoRepository,
        library_repo: LibraryRepository,
    ):
        self.channel_repo = channel_repo
        self.video_repo = video_repo
        self.library_repo = library_repo

    async def get_or_create_reference_library(self, org_id: UUID) -> Library:
        existing = await self.library_repo.get_by_name(org_id, REFERENCE_LIBRARY_NAME)
        if existing is not None:
            return existing

        created = await self.library_repo.create(org_id=org_id, name=REFERENCE_LIBRARY_NAME)
        logger.info(
            "youtube_reference_library_created",
            org_id=str(org_id),
            library_id=str(created.id),
            library_name=REFERENCE_LIBRARY_NAME,
        )
        return created

    def resolve_channel_identity(
        self,
        channel_url: str,
        channel_name: str | None,
    ) -> tuple[str, str]:
        normalized = channel_url.strip()
        if not normalized:
            raise ValueError("channel_url is required")

        direct_match = _CHANNEL_ID_RE.match(normalized)
        if direct_match is not None:
            channel_id = direct_match.group(1)
            return channel_id, channel_name or channel_id

        if not _CHANNEL_URL_RE.search(normalized):
            raise ValueError("Unsupported YouTube channel URL")

        channel_id = self._extract_channel_id_from_url(normalized)
        if channel_id is not None:
            default_name = channel_name or channel_id
            return channel_id, default_name

        handle = self._extract_handle_from_url(normalized)
        if handle is None:
            raise ValueError("Could not resolve channel ID from URL")

        synthetic_channel_id = self._handle_to_channel_id(handle)
        display_name = channel_name or f"@{handle}"
        return synthetic_channel_id, display_name

    async def register_channel(
        self,
        *,
        org_id: UUID,
        channel_url: str,
        channel_name: str | None,
    ) -> YouTubeChannel:
        await self.get_or_create_reference_library(org_id)

        resolved_channel_id, resolved_name = self.resolve_channel_identity(
            channel_url=channel_url,
            channel_name=channel_name,
        )

        existing = await self.channel_repo.get_by_channel_id(org_id, resolved_channel_id)
        if existing is not None:
            return existing

        return await self.channel_repo.create(
            org_id=org_id,
            channel_id=resolved_channel_id,
            channel_url=channel_url,
            channel_name=resolved_name,
        )

    async def create_video_record(
        self,
        *,
        org_id: UUID,
        channel: YouTubeChannel,
        request: CreateYouTubeVideoRequest,
    ) -> YouTubeVideo:
        existing = await self.video_repo.get_by_youtube_video_id(org_id, request.youtube_video_id)
        if existing is not None:
            return existing

        video = await self.video_repo.create(
            org_id=org_id,
            channel_id=cast(UUID, channel.id),
            youtube_video_id=request.youtube_video_id,
            video_id=self.generate_video_id(org_id, request.youtube_video_id),
            title=request.title,
            description=request.description,
            duration_seconds=request.duration_seconds,
            publish_date=request.publish_date,
            thumbnail_url=request.thumbnail_url,
            enrichment_status={"subtitle": "pending"},
        )
        await self.channel_repo.set_video_count(channel, channel.video_count + 1)
        return video

    def inject_subtitle_status(
        self,
        *,
        video: YouTubeVideo,
        subtitle_language: str | None,
        has_subtitles: bool | None,
    ) -> None:
        if subtitle_language is not None:
            video.subtitle_language = subtitle_language
            video.has_subtitles = True

        if has_subtitles is not None:
            video.has_subtitles = has_subtitles
            if not has_subtitles:
                video.subtitle_language = None

        status = dict(video.enrichment_status or {})
        status["subtitle"] = "complete" if video.has_subtitles else "skipped"
        video.enrichment_status = status

    @staticmethod
    def generate_video_id(org_id: UUID, youtube_video_id: str) -> str:
        digest = hashlib.sha256(f"{org_id}:{youtube_video_id}".encode()).hexdigest()[:16]
        return f"yt_{digest}"

    @staticmethod
    def _extract_channel_id_from_url(channel_url: str) -> str | None:
        marker = "/channel/"
        if marker not in channel_url:
            return None
        channel_part = channel_url.split(marker, 1)[1].split("?", 1)[0].split("/", 1)[0]
        if _CHANNEL_ID_RE.match(channel_part):
            return channel_part
        return None

    @staticmethod
    def _extract_handle_from_url(channel_url: str) -> str | None:
        match = re.search(r"@([a-zA-Z0-9._-]+)", channel_url)
        if match is None:
            return None
        return match.group(1)

    @staticmethod
    def _handle_to_channel_id(handle: str) -> str:
        digest = hashlib.sha256(handle.lower().encode()).hexdigest()[:22]
        return f"UC{digest}"
