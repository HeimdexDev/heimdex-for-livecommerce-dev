"""Highlight reel API endpoints.

Mounted under /api/people/{person_cluster_id}/highlight-reel.
"""
from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.dependencies import (
    get_db_session,
    get_people_video_exclusion_repository,
    get_scene_opensearch_client,
    get_shorts_render_service,
)
from app.logging_config import get_logger
from app.modules.auth import get_current_user
from app.modules.highlight_reel.adapter import OpenSearchSceneDataAdapter
from app.modules.highlight_reel.schemas import (
    HighlightReelPreviewRequest,
    HighlightReelPreviewResponse,
    HighlightReelRenderRequest,
)
from app.modules.highlight_reel.service import HighlightReelService
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org

logger = get_logger(__name__)

router = APIRouter(tags=["highlight-reel"])


@router.post("/preview", response_model=HighlightReelPreviewResponse)
async def generate_highlight_preview(
    person_cluster_id: str,
    request: HighlightReelPreviewRequest,
    org_ctx: OrgContext = Depends(get_current_org),
    user=Depends(get_current_user),
    scene_client=Depends(get_scene_opensearch_client),
    video_excl_repo=Depends(get_people_video_exclusion_repository),
):
    settings = get_settings()
    if not settings.people_enabled or not settings.highlight_reel_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Highlight reel feature is not enabled")

    adapter = OpenSearchSceneDataAdapter(scene_client, video_excl_repo)
    service = HighlightReelService(adapter)

    preview = await service.generate_preview(
        org_id=str(org_ctx.org_id),
        user_id=cast(UUID, user.id),
        person_cluster_id=person_cluster_id,
        target_duration_s=request.target_duration_s,
    )

    if not preview.clips:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No eligible scenes found for this person",
        )

    return preview


@router.post("/render")
async def render_highlight_reel(
    person_cluster_id: str,
    request: HighlightReelRenderRequest,
    org_ctx: OrgContext = Depends(get_current_org),
    user=Depends(get_current_user),
    render_service=Depends(get_shorts_render_service),
    db: AsyncSession = Depends(get_db_session),
):
    settings = get_settings()
    if not settings.people_enabled or not settings.highlight_reel_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Highlight reel feature is not enabled")

    if not request.clips:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one clip is required",
        )

    from heimdex_media_contracts.composition import CompositionSpec
    from app.modules.shorts_render.schemas import RenderJobCreate

    comp_dict = HighlightReelService.build_composition_dict(request.clips)
    composition = CompositionSpec(**comp_dict)

    payload = RenderJobCreate(
        video_id=f"highlight:{person_cluster_id}",
        title=request.title or f"Highlight: {person_cluster_id}",
        composition=composition,
    )

    logger.info(
        "highlight_reel_render_submitted",
        org_id=str(org_ctx.org_id),
        person_cluster_id=person_cluster_id,
        clip_count=len(request.clips),
        total_duration_ms=sum(c.duration_ms for c in request.clips),
    )

    result = await render_service.create_render_job(
        org_id=org_ctx.org_id,
        user_id=cast(UUID, user.id),
        payload=payload,
    )

    await db.commit()

    return result
