"""API endpoints for video summary generation and editing."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.dependencies import get_db_session, get_scene_opensearch_client
from app.logging_config import get_logger
from app.modules.auth import get_current_user
from app.modules.tenancy import OrgContext, get_current_org
from app.modules.users.models import User
from app.modules.video_summary.repository import VideoSummaryRepository
from app.modules.video_summary.schemas import (
    VideoSummaryEditRequest,
    VideoSummaryGenerateRequest,
    VideoSummaryResponse,
)
from app.modules.video_summary.service import VideoSummaryService

logger = get_logger(__name__)

router = APIRouter(
    prefix="/videos/{video_id}/summary",
    tags=["video-summary"],
)


def _get_service(
    session: AsyncSession = Depends(get_db_session),
    scene_client=Depends(get_scene_opensearch_client),
) -> VideoSummaryService:
    settings = get_settings()
    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    repo = VideoSummaryRepository(session)
    return VideoSummaryService(
        repo=repo,
        scene_client=scene_client,
        openai_client=openai_client,
        model=settings.video_summary_model,
    )


@router.get("", response_model=VideoSummaryResponse)
async def get_video_summary(
    video_id: str,
    org: OrgContext = Depends(get_current_org),
    service: VideoSummaryService = Depends(_get_service),
):
    result = await service.get_summary(org.org_id, video_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No summary exists for this video")
    return result


@router.post("/generate", response_model=VideoSummaryResponse)
async def generate_video_summary(
    video_id: str,
    body: VideoSummaryGenerateRequest = VideoSummaryGenerateRequest(),
    org: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    service: VideoSummaryService = Depends(_get_service),
):
    settings = get_settings()
    if not settings.video_summary_enabled:
        raise HTTPException(status_code=403, detail="Video summary feature is not enabled")

    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OpenAI API key not configured")

    try:
        return await service.generate(org.org_id, video_id, force=body.force)
    except Exception:
        logger.exception("video_summary_generate_failed", video_id=video_id)
        raise HTTPException(status_code=502, detail="Failed to generate video summary")


@router.patch("", response_model=VideoSummaryResponse)
async def edit_video_summary(
    video_id: str,
    body: VideoSummaryEditRequest,
    org: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    service: VideoSummaryService = Depends(_get_service),
):
    result = await service.edit_summary(org.org_id, video_id, body.summary, user.id)
    if result is None:
        raise HTTPException(status_code=404, detail="No summary exists for this video. Generate one first.")
    return result


@router.delete("/override", response_model=VideoSummaryResponse)
async def reset_video_summary(
    video_id: str,
    org: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    service: VideoSummaryService = Depends(_get_service),
):
    result = await service.reset_summary(org.org_id, video_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No summary exists for this video")
    return result
