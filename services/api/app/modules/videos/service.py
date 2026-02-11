"""
Video visibility service.

Thin orchestration layer: delegates to SceneSearchClient for aggregation,
enriches with library names from Postgres.
"""
import base64
import json
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import get_logger
from app.modules.libraries.repository import LibraryRepository
from app.modules.search.scene_client import SceneSearchClient
from app.modules.videos.schemas import (
    VideoFacetItem,
    VideoFacets,
    VideoListResponse,
    VideoScene,
    VideoScenesResponse,
    VideoStats,
    VideoSummary,
)

logger = get_logger(__name__)


class VideoService:
    """Derives video-level views from OpenSearch scene aggregations."""

    def __init__(self, session: AsyncSession, scene_client: SceneSearchClient):
        self.session = session
        self.scene_client = scene_client

    async def list_videos(
        self,
        org_id: UUID,
        *,
        library_id: str | None = None,
        source_type: str | None = None,
        sort: str = "latest",
        page_size: int = 20,
        after_cursor: str | None = None,
    ) -> VideoListResponse:
        """List ingested videos for an org via OpenSearch aggregation."""
        # Decode cursor
        after_key = None
        if after_cursor:
            try:
                after_key = json.loads(base64.urlsafe_b64decode(after_cursor))
            except Exception:
                logger.warning("invalid_video_cursor", cursor=after_cursor)

        result = await self.scene_client.aggregate_videos(
            str(org_id),
            library_id=library_id,
            source_type=source_type,
            sort=sort,
            page_size=page_size,
            after_key=after_key,
        )

        # Enrich with library names
        library_repo = LibraryRepository(self.session)
        libraries = await library_repo.list_by_org(org_id)
        library_map = {str(lib.id): lib.name for lib in libraries}

        videos = [
            VideoSummary(
                video_id=v["video_id"],
                video_title=v["video_title"],
                library_id=v["library_id"],
                library_name=library_map.get(v["library_id"] or "", "Unknown"),
                source_type=v["source_type"],
                scene_count=v["scene_count"],
                first_scene_start_ms=v["first_scene_start_ms"],
                last_scene_end_ms=v["last_scene_end_ms"],
                earliest_ingest_time=v["earliest_ingest_time"],
                latest_ingest_time=v["latest_ingest_time"],
                keyword_tags=v["keyword_tags"],
                product_tags=v["product_tags"],
                people_count=v["people_count"],
                required_drive_nickname=v["required_drive_nickname"],
            )
            for v in result["videos"]
        ]

        # Encode next cursor
        next_cursor = None
        if result["next_cursor"]:
            next_cursor = base64.urlsafe_b64encode(
                json.dumps(result["next_cursor"]).encode()
            ).decode()

        facets = VideoFacets(
            libraries=[
                VideoFacetItem(
                    id=bucket["key"],
                    name=library_map.get(bucket["key"]),
                    count=bucket["doc_count"],
                )
                for bucket in result["facets"]["libraries"]
            ],
            source_types=[
                VideoFacetItem(
                    id=bucket["key"],
                    name=bucket["key"],
                    count=bucket["doc_count"],
                )
                for bucket in result["facets"]["source_types"]
            ],
        )

        logger.info(
            "videos_listed",
            org_id=str(org_id),
            video_count=len(videos),
            total=result["total"],
        )

        return VideoListResponse(
            videos=videos,
            total=result["total"],
            next_cursor=next_cursor,
            facets=facets,
        )

    async def get_video_scenes(
        self,
        org_id: UUID,
        video_id: str,
        *,
        page_size: int = 50,
        offset: int = 0,
    ) -> VideoScenesResponse:
        """Get scenes for a specific video."""
        result = await self.scene_client.get_video_scenes(
            str(org_id),
            video_id,
            page_size=page_size,
            offset=offset,
        )

        scenes = [VideoScene(**s) for s in result["scenes"]]

        return VideoScenesResponse(
            video_id=video_id,
            scenes=scenes,
            total=result["total"],
        )

    async def get_stats(self, org_id: UUID) -> VideoStats:
        """Get summary statistics for all ingested videos."""
        result = await self.scene_client.get_video_stats(str(org_id))
        return VideoStats(**result)
