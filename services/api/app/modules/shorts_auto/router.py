"""HTTP routes for /api/shorts/auto-*.

Two endpoints:
  - POST /api/shorts/auto-select  → preview only, no side effects
  - POST /api/shorts/auto-render  → preview + delegate to render pipeline

Both endpoints 404 when ``Settings.auto_shorts_enabled`` is False so the
feature can be merged dark and flipped per-environment.
"""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import get_settings
from app.dependencies import (
    get_drive_file_repository,
    get_scene_opensearch_client,
    get_shorts_render_service,
)
from app.modules.auth.service import get_current_user
from app.modules.shorts_auto.rate_limit import require_auto_shorts_rate_limit
from app.modules.shorts_auto.schemas import (
    AutoRenderRequest,
    AutoSelectRequest,
    AutoSelectResponse,
)
from app.modules.shorts_auto.scorers import build_scorer, should_use_llm_for_request
from app.modules.shorts_auto.selector import AutoShortsSelector
from app.modules.shorts_auto.service import ShortsAutoService
from app.modules.shorts_render.schemas import RenderJobResponse
from app.modules.shorts_render.service import ShortsRenderService
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org
from app.modules.users.models import User

router = APIRouter(prefix="/shorts", tags=["shorts-auto"])


def get_shorts_auto_service(
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    scene_opensearch=Depends(get_scene_opensearch_client),
    drive_file_repo=Depends(get_drive_file_repository),
    shorts_render_service: ShortsRenderService = Depends(get_shorts_render_service),
) -> ShortsAutoService:
    # The rollout decision is made once per request at DI time, not on
    # every scorer.score() call, so a flag flip mid-request doesn't race.
    # The video_id isn't known at DI time (it's in the request body), so
    # we use org_id + the feature flag only. Per-video bucketing lives
    # inside should_use_llm_for_request once wired via a post-DI layer.
    settings = get_settings()
    use_llm = should_use_llm_for_request(
        settings, org_id=org_ctx.org_id, video_id=""
    )
    return ShortsAutoService(
        selector=AutoShortsSelector(scene_opensearch),
        drive_file_repo=drive_file_repo,
        shorts_render_service=shorts_render_service,
        scorer=build_scorer(settings, use_llm=use_llm),
    )


def _enforce_feature_flag() -> None:
    if not get_settings().auto_shorts_enabled:
        # 404 (not 403) so the feature is invisible to clients that
        # haven't been told about it. Same pattern as ``BLUR_ENABLED``.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not Found",
        )


@router.get(
    "/auto-availability",
    status_code=status.HTTP_200_OK,
)
async def auto_availability(
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, bool]:
    """Feature-detect probe for the frontend.

    200 ``{"enabled": true, "llm_enabled": bool}`` when the master flag
    is on; 404 when off. Authoritative — checks the flag BEFORE any body
    validation so the signal is reliable across flag flips (unlike
    sending an invalid body to auto-select, where Pydantic fires 422
    first regardless of the flag state).

    ``llm_enabled`` tells the UI whether to show the "AI mode" toggle.
    Derived from ``auto_shorts_llm_enabled`` AND rollout_pct > 0 so a
    0% rollout correctly hides the toggle. Per-video bucketing applies
    at request time; this probe is per-org coarse.

    Intentionally has no body + no rate-limit dependency so rendering
    a CTA doesn't burn user render budget.
    """
    _enforce_feature_flag()
    settings = get_settings()
    llm_enabled = bool(
        getattr(settings, "auto_shorts_llm_enabled", False)
    ) and int(getattr(settings, "auto_shorts_llm_rollout_pct", 0) or 0) > 0
    return {"enabled": True, "llm_enabled": llm_enabled}


@router.post(
    "/auto-select",
    response_model=AutoSelectResponse,
    status_code=status.HTTP_200_OK,
)
async def auto_select(
    body: AutoSelectRequest,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ShortsAutoService, Depends(get_shorts_auto_service)],
    _rate_limit: Annotated[None, Depends(require_auto_shorts_rate_limit)] = None,
):
    _enforce_feature_flag()
    user_id = cast(UUID, user.id)
    return await service.auto_select(org_ctx.org_id, user_id, body)


@router.post(
    "/auto-render",
    response_model=RenderJobResponse,
    status_code=status.HTTP_201_CREATED,
)
async def auto_render(
    body: AutoRenderRequest,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ShortsAutoService, Depends(get_shorts_auto_service)],
    _rate_limit: Annotated[None, Depends(require_auto_shorts_rate_limit)] = None,
):
    _enforce_feature_flag()
    user_id = cast(UUID, user.id)
    return await service.auto_render(org_ctx.org_id, user_id, body)
