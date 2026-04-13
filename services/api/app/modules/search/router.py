import asyncio
import time
from typing import Any, cast
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


async def _record_search_event(
    *,
    org_id: UUID,
    user_id: UUID,
    query_text: str,
    search_mode: str,
    result_count: int | None,
    response_ms: int | None,
    extra_metadata: dict[str, Any] | None = None,
) -> None:
    """Fire-and-forget search event recording.

    Creates its own short-lived DB session — the request session may already
    be closed by the time this background task runs.
    Failures are logged and swallowed — analytics must never block search.
    """
    try:
        from app.db.base import get_async_session_factory
        from app.modules.search.search_event_repository import SearchEventRepository

        factory = get_async_session_factory()
        async with factory() as session:
            repo = SearchEventRepository(session)
            await repo.create(
                org_id=org_id,
                user_id=user_id,
                query_text=query_text,
                search_mode=search_mode,
                result_count=result_count,
                response_ms=response_ms,
                metadata=extra_metadata,
            )
            await session.commit()
    except Exception:
        logger.warning("search_event_recording_failed", exc_info=True)


def _extract_result_count(response: Any) -> int | None:
    if hasattr(response, "total_candidates"):
        return response.total_candidates
    return None


def _build_metadata(request: SearchRequest) -> dict[str, Any]:
    meta: dict[str, Any] = {"alpha": request.alpha, "group_by": request.group_by}
    if request.filters.date_from:
        meta["date_from"] = request.filters.date_from.isoformat()
    if request.filters.date_to:
        meta["date_to"] = request.filters.date_to.isoformat()
    if request.filters.source_types:
        meta["source_types"] = list(request.filters.source_types)
    if request.filters.person_cluster_ids:
        meta["person_cluster_ids"] = request.filters.person_cluster_ids
    if request.include_ocr is not None:
        meta["include_ocr"] = request.include_ocr
    if request.color_family:
        meta["color_family"] = request.color_family
    elif request.color_hex:
        meta["color_hex"] = request.color_hex
    if request.page_size is not None:
        meta["page_size_requested"] = request.page_size
    if request.max_per_video is not None:
        meta["max_per_video_requested"] = request.max_per_video
    settings = get_settings()
    if settings.reranker_enabled:
        meta["reranker_enabled"] = True
    return meta


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
    t0 = time.monotonic()

    if settings.search_default_mode == "scenes":
        result = await scene_search_service.search(
            query=request.q,
            org_id=org_ctx.org_id,
            alpha=request.alpha,
            filters=request.filters,
            include_ocr=request.include_ocr,
            user_id=user_id,
            group_by=request.group_by,
            search_mode=request.search_mode,
            color_hex=request.color_hex,
            color_family=request.color_family,
            page_size=request.page_size,
            max_per_video=request.max_per_video,
        )
    else:
        result = await search_service.search(
            query=request.q,
            org_id=org_ctx.org_id,
            alpha=request.alpha,
            filters=request.filters,
            user_id=user_id,
        )

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    if settings.analytics_enabled:
        asyncio.create_task(
            _record_search_event(
                org_id=org_ctx.org_id,
                user_id=user_id,
                query_text=request.q,
                search_mode=request.search_mode,
                result_count=_extract_result_count(result),
                response_ms=elapsed_ms,
                extra_metadata=_build_metadata(request),
            )
        )

    return result


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
    settings = get_settings()
    logger.debug(
        "scene_search_request",
        user_id=str(user.id),
        org_id=str(org_ctx.org_id),
        search_mode=request.search_mode,
    )
    user_id = cast(UUID, user.id)
    t0 = time.monotonic()

    result = await scene_search_service.search(
        query=request.q,
        org_id=org_ctx.org_id,
        alpha=request.alpha,
        filters=request.filters,
        include_ocr=request.include_ocr,
        user_id=user_id,
        group_by=request.group_by,
        search_mode=request.search_mode,
        color_hex=request.color_hex,
        color_family=request.color_family,
        page_size=request.page_size,
        max_per_video=request.max_per_video,
    )

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    if settings.analytics_enabled:
        asyncio.create_task(
            _record_search_event(
                org_id=org_ctx.org_id,
                user_id=user_id,
                query_text=request.q,
                search_mode=request.search_mode,
                result_count=_extract_result_count(result),
                response_ms=elapsed_ms,
                extra_metadata=_build_metadata(request),
            )
        )

    return result
