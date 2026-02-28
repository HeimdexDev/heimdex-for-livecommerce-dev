from typing import cast
from uuid import UUID

from fastapi import APIRouter, Depends

from app.config import get_settings
from app.dependencies import get_scene_search_service, get_search_service
from app.logging_config import get_logger
from app.modules.auth import get_current_user
from app.modules.search.rate_limit import require_search_rate_limit
from app.modules.search.scene_service import SceneSearchService
from app.modules.search.schemas import (
    SceneSearchResponse,
    SearchRequest,
    SearchResponse,
    VideoSearchResponse,
)
from app.modules.search.service import SearchService
from app.modules.tenancy import OrgContext, get_current_org
from app.modules.users.models import User

logger = get_logger(__name__)
router = APIRouter(prefix="/search", tags=["search"])


@router.post("")
async def search(
    request: SearchRequest,
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    search_service: SearchService = Depends(get_search_service),
    scene_search_service: SceneSearchService = Depends(get_scene_search_service),
    _rate_limit=Depends(require_search_rate_limit),
):
    """Unified search endpoint.

    Routes to segment or scene search based on ``SEARCH_DEFAULT_MODE``.
    Rollback: flip the env var — no code change needed.
    """
    settings = get_settings()

    logger.debug(
        "search_request",
        user_id=str(user.id),
        org_id=str(org_ctx.org_id),
        mode=settings.search_default_mode,
        search_mode=request.search_mode,
    )

    user_id = cast(UUID, user.id)

    if settings.search_default_mode == "scenes":
        return await scene_search_service.search(
            query=request.q,
            org_id=org_ctx.org_id,
            alpha=request.alpha,
            filters=request.filters,
            include_ocr=request.include_ocr,
            user_id=user_id,
            group_by=request.group_by,
            search_mode=request.search_mode,
        )

    return await search_service.search(
        query=request.q,
        org_id=org_ctx.org_id,
        alpha=request.alpha,
        filters=request.filters,
        user_id=user_id,
    )


@router.post("/scenes", response_model=SceneSearchResponse | VideoSearchResponse)
async def search_scenes(
    request: SearchRequest,
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    scene_search_service: SceneSearchService = Depends(get_scene_search_service),
    _rate_limit=Depends(require_search_rate_limit),
):
    """Dedicated scene search endpoint.

    Always returns scene results regardless of ``SEARCH_DEFAULT_MODE``.
    """
    logger.debug(
        "scene_search_request",
        user_id=str(user.id),
        org_id=str(org_ctx.org_id),
        search_mode=request.search_mode,
    )
    user_id = cast(UUID, user.id)
    return await scene_search_service.search(
        query=request.q,
        org_id=org_ctx.org_id,
        alpha=request.alpha,
        filters=request.filters,
        include_ocr=request.include_ocr,
        user_id=user_id,
        group_by=request.group_by,
        search_mode=request.search_mode,
    )
