"""
Video visibility router.

Endpoints:
  GET /api/videos          - List ingested videos (aggregated from scenes)
  GET /api/videos/stats    - Summary statistics
  GET /api/videos/{video_id}/scenes - Scenes for a specific video
"""
from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.dependencies import get_video_service
from app.logging_config import get_logger
from app.modules.auth import get_current_user
from app.modules.tenancy import OrgContext, get_current_org
from app.modules.users.models import User
from app.modules.videos.schemas import (
    VideoListResponse,
    VideoScenesResponse,
    VideoStats,
)
from app.modules.videos.service import VideoService

logger = get_logger(__name__)
router = APIRouter(prefix="/videos", tags=["videos"])


@router.get("", response_model=VideoListResponse)
async def list_videos(
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    video_service: VideoService = Depends(get_video_service),
    library_id: str | None = Query(None, description="Filter by library UUID"),
    source_type: Literal["gdrive", "removable_disk", "local"] | None = Query(None, description="Filter by source type"),
    sort: Literal["latest", "oldest"] = Query("latest", description="Sort order by ingest time"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    after: str | None = Query(None, description="Cursor for next page"),
):
    """List all ingested videos for the authenticated user's org."""
    logger.debug(
        "list_videos_request",
        user_id=str(user.id),
        org_id=str(org_ctx.org_id),
        library_id=library_id,
        source_type=source_type,
        sort=sort,
    )

    return await video_service.list_videos(
        org_ctx.org_id,
        library_id=library_id,
        source_type=source_type,
        sort=sort,
        page_size=page_size,
        after_cursor=after,
    )


@router.get("/stats", response_model=VideoStats)
async def video_stats(
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    video_service: VideoService = Depends(get_video_service),
):
    """Get summary statistics for all ingested videos."""
    logger.debug(
        "video_stats_request",
        user_id=str(user.id),
        org_id=str(org_ctx.org_id),
    )

    return await video_service.get_stats(org_ctx.org_id)


@router.get("/{video_id}/scenes", response_model=VideoScenesResponse)
async def video_scenes(
    video_id: str,
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    video_service: VideoService = Depends(get_video_service),
    page_size: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """Get all scenes for a specific video."""
    logger.debug(
        "video_scenes_request",
        user_id=str(user.id),
        org_id=str(org_ctx.org_id),
        video_id=video_id,
    )

    return await video_service.get_video_scenes(
        org_ctx.org_id,
        video_id,
        page_size=page_size,
        offset=offset,
    )
