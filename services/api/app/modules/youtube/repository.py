from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import YouTubeChannel, YouTubeVideo


class YouTubeChannelRepository:
    def __init__(self, session: AsyncSession):
        self.session: AsyncSession = session

    async def create(
        self,
        *,
        org_id: UUID,
        channel_id: str,
        channel_url: str,
        channel_name: str,
        thumbnail_url: str | None = None,
        sync_enabled: bool = True,
    ) -> YouTubeChannel:
        channel = YouTubeChannel(
            org_id=org_id,
            channel_id=channel_id,
            channel_url=channel_url,
            channel_name=channel_name,
            thumbnail_url=thumbnail_url,
            sync_enabled=sync_enabled,
        )
        self.session.add(channel)
        await self.session.flush()
        return channel

    async def get_by_id(self, channel_pk: UUID, org_id: UUID) -> YouTubeChannel | None:
        result = await self.session.execute(
            select(YouTubeChannel).where(
                YouTubeChannel.id == channel_pk,
                YouTubeChannel.org_id == org_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id_resource_scoped(
        self, channel_pk: UUID,
    ) -> YouTubeChannel | None:
        """Look up a channel by id alone — no ``org_id`` filter.

        Used by the Pattern B internal-auth flow (see
        ``app/lib/internal_auth.py``). Caller derives ``org_id`` from
        the returned row's ``.org_id`` attribute. Specifically NOT
        the default — Pattern A callers continue to use
        ``get_by_id(pk, org_id)`` so this method can't accidentally
        regress them to F1's caller-asserted org-binding.
        """
        result = await self.session.execute(
            select(YouTubeChannel).where(YouTubeChannel.id == channel_pk)
        )
        return result.scalar_one_or_none()

    async def get_by_channel_id(self, org_id: UUID, channel_id: str) -> YouTubeChannel | None:
        result = await self.session.execute(
            select(YouTubeChannel).where(
                YouTubeChannel.org_id == org_id,
                YouTubeChannel.channel_id == channel_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_org(
        self,
        org_id: UUID,
        *,
        sync_enabled: bool | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[YouTubeChannel]:
        query = (
            select(YouTubeChannel)
            .where(YouTubeChannel.org_id == org_id)
            .order_by(YouTubeChannel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if sync_enabled is not None:
            query = query.where(YouTubeChannel.sync_enabled.is_(sync_enabled))

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def count_by_org(self, org_id: UUID, *, sync_enabled: bool | None = None) -> int:
        query = select(func.count()).select_from(YouTubeChannel).where(YouTubeChannel.org_id == org_id)
        if sync_enabled is not None:
            query = query.where(YouTubeChannel.sync_enabled.is_(sync_enabled))
        result = await self.session.execute(query)
        return int(result.scalar_one())

    async def update(
        self,
        channel: YouTubeChannel,
        *,
        channel_url: str | None = None,
        channel_name: str | None = None,
        thumbnail_url: str | None = None,
        sync_enabled: bool | None = None,
    ) -> YouTubeChannel:
        if channel_url is not None:
            channel.channel_url = channel_url
        if channel_name is not None:
            channel.channel_name = channel_name
        if thumbnail_url is not None:
            channel.thumbnail_url = thumbnail_url
        if sync_enabled is not None:
            channel.sync_enabled = sync_enabled
        await self.session.flush()
        return channel

    async def update_last_synced_at(
        self,
        channel: YouTubeChannel,
        *,
        synced_at: datetime | None = None,
    ) -> YouTubeChannel:
        channel.last_synced_at = synced_at or datetime.now(UTC)
        await self.session.flush()
        return channel

    async def set_video_count(self, channel: YouTubeChannel, video_count: int) -> YouTubeChannel:
        channel.video_count = max(0, video_count)
        await self.session.flush()
        return channel

    async def delete(self, channel: YouTubeChannel) -> None:
        await self.session.delete(channel)
        await self.session.flush()


class YouTubeVideoRepository:
    def __init__(self, session: AsyncSession):
        self.session: AsyncSession = session

    async def create(
        self,
        *,
        org_id: UUID,
        channel_id: UUID,
        youtube_video_id: str,
        video_id: str,
        title: str,
        description: str | None = None,
        duration_seconds: int | None = None,
        publish_date: datetime | None = None,
        thumbnail_url: str | None = None,
        subtitle_language: str | None = None,
        has_subtitles: bool = False,
        processing_status: str = "pending",
        enrichment_status: dict[str, str] | None = None,
    ) -> YouTubeVideo:
        video = YouTubeVideo(
            org_id=org_id,
            channel_id=channel_id,
            youtube_video_id=youtube_video_id,
            video_id=video_id,
            title=title,
            description=description,
            duration_seconds=duration_seconds,
            publish_date=publish_date,
            thumbnail_url=thumbnail_url,
            subtitle_language=subtitle_language,
            has_subtitles=has_subtitles,
            processing_status=processing_status,
            enrichment_status=enrichment_status or {},
        )
        self.session.add(video)
        await self.session.flush()
        return video

    async def get_by_id(self, video_pk: UUID, org_id: UUID) -> YouTubeVideo | None:
        result = await self.session.execute(
            select(YouTubeVideo).where(
                YouTubeVideo.id == video_pk,
                YouTubeVideo.org_id == org_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id_resource_scoped(
        self, video_pk: UUID,
    ) -> YouTubeVideo | None:
        """Pattern B lookup — see ``YouTubeChannelRepository.get_by_id_resource_scoped``
        for the full design rationale."""
        result = await self.session.execute(
            select(YouTubeVideo).where(YouTubeVideo.id == video_pk)
        )
        return result.scalar_one_or_none()

    async def get_by_youtube_video_id(self, org_id: UUID, youtube_video_id: str) -> YouTubeVideo | None:
        result = await self.session.execute(
            select(YouTubeVideo).where(
                YouTubeVideo.org_id == org_id,
                YouTubeVideo.youtube_video_id == youtube_video_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_video_id(self, org_id: UUID, video_id: str) -> YouTubeVideo | None:
        result = await self.session.execute(
            select(YouTubeVideo).where(
                YouTubeVideo.org_id == org_id,
                YouTubeVideo.video_id == video_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_channel(
        self,
        *,
        org_id: UUID,
        channel_id: UUID,
        limit: int = 200,
        offset: int = 0,
    ) -> list[YouTubeVideo]:
        result = await self.session.execute(
            select(YouTubeVideo)
            .where(
                YouTubeVideo.org_id == org_id,
                YouTubeVideo.channel_id == channel_id,
            )
            .order_by(YouTubeVideo.publish_date.desc().nullslast(), YouTubeVideo.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_org(
        self,
        *,
        org_id: UUID,
        processing_status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[YouTubeVideo]:
        query = (
            select(YouTubeVideo)
            .where(YouTubeVideo.org_id == org_id)
            .order_by(YouTubeVideo.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if processing_status is not None:
            query = query.where(YouTubeVideo.processing_status == processing_status)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def count_by_channel(self, *, org_id: UUID, channel_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(YouTubeVideo)
            .where(
                YouTubeVideo.org_id == org_id,
                YouTubeVideo.channel_id == channel_id,
            )
        )
        return int(result.scalar_one())

    async def list_known_youtube_video_ids(self, *, org_id: UUID, channel_id: UUID) -> list[str]:
        result = await self.session.execute(
            select(YouTubeVideo.youtube_video_id)
            .where(
                YouTubeVideo.org_id == org_id,
                YouTubeVideo.channel_id == channel_id,
            )
            .order_by(YouTubeVideo.created_at.desc())
        )
        return [row[0] for row in result.all()]

    async def list_cleanup_candidates(self, *, org_id: UUID, limit: int = 200) -> list[YouTubeVideo]:
        result = await self.session.execute(
            select(YouTubeVideo)
            .where(
                YouTubeVideo.org_id == org_id,
                YouTubeVideo.processing_status == "complete",
                YouTubeVideo.original_deleted.is_(False),
            )
            .order_by(YouTubeVideo.updated_at.asc())
            .limit(limit)
        )
        candidates = list(result.scalars().all())
        return [video for video in candidates if _is_enrichment_complete(video.enrichment_status)]

    async def list_pending(self, *, org_id: UUID, limit: int = 5) -> list[YouTubeVideo]:
        result = await self.session.execute(
            select(YouTubeVideo)
            .where(
                YouTubeVideo.org_id == org_id,
                YouTubeVideo.processing_status == "pending",
            )
            .order_by(YouTubeVideo.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def update_status(
        self,
        *,
        video: YouTubeVideo,
        processing_status: str,
        subtitle_language: str | None = None,
        has_subtitles: bool | None = None,
        enrichment_status: dict[str, str] | None = None,
        original_deleted: bool | None = None,
    ) -> YouTubeVideo:
        video.processing_status = processing_status
        if subtitle_language is not None:
            video.subtitle_language = subtitle_language
        if has_subtitles is not None:
            video.has_subtitles = has_subtitles
        if enrichment_status is not None:
            video.enrichment_status = enrichment_status
        if original_deleted is not None:
            video.original_deleted = original_deleted

        await self.session.flush()
        return video

    async def mark_original_deleted(self, video: YouTubeVideo) -> YouTubeVideo:
        video.original_deleted = True
        await self.session.flush()
        return video

    async def get_web_view_links(
        self, org_id: UUID, video_ids: list[str],
    ) -> dict[str, str]:
        """Map internal video_ids (yt_*) to YouTube watch URLs."""
        if not video_ids:
            return {}
        result = await self.session.execute(
            select(YouTubeVideo.video_id, YouTubeVideo.youtube_video_id)
            .where(
                YouTubeVideo.org_id == org_id,
                YouTubeVideo.video_id.in_(video_ids),
            )
        )
        return {
            row.video_id: f"https://www.youtube.com/watch?v={row.youtube_video_id}"
            for row in result.all()
        }

    async def delete(self, video: YouTubeVideo) -> None:
        await self.session.delete(video)
        await self.session.flush()


def _is_enrichment_complete(enrichment_status: dict[str, str] | None) -> bool:
    if not enrichment_status:
        return False
    statuses = [str(value) for value in enrichment_status.values()]
    if not statuses:
        return False
    return all(status in {"complete", "skipped"} for status in statuses)
