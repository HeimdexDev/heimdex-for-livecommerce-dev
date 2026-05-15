"""FastAPI router for subtitle presets.

Routes (mounted under /api):
- GET    /shorts/presets           — list visible (own ∪ org-shared)
- POST   /shorts/presets           — create (rate-limited)
- PATCH  /shorts/presets/{id}      — update (rate-limited; owner-only)
- DELETE /shorts/presets/{id}      — delete (rate-limited; owner-only)
"""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.dependencies import get_subtitle_preset_service
from app.modules.auth.service import get_current_user
from app.modules.subtitle_presets.rate_limit import (
    require_subtitle_preset_rate_limit,
)
from app.modules.subtitle_presets.schemas import (
    PresetCreate,
    PresetKind,
    PresetListResponse,
    PresetResponse,
    PresetUpdate,
)
from app.modules.subtitle_presets.service import SubtitlePresetService
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org
from app.modules.users.models import User

router = APIRouter(prefix="/shorts/presets", tags=["subtitle-presets"])


@router.get("", response_model=PresetListResponse)
async def list_presets(
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        SubtitlePresetService, Depends(get_subtitle_preset_service)
    ],
    kind: PresetKind | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    user_id = cast(UUID, user.id)
    return await service.list(
        org_id=org_ctx.org_id,
        user_id=user_id,
        kind=kind,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=PresetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_preset(
    body: PresetCreate,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        SubtitlePresetService, Depends(get_subtitle_preset_service)
    ],
    _rate_limit: Annotated[None, Depends(require_subtitle_preset_rate_limit)] = None,
):
    user_id = cast(UUID, user.id)
    return await service.create(
        org_id=org_ctx.org_id, user_id=user_id, body=body
    )


@router.patch("/{preset_id}", response_model=PresetResponse)
async def update_preset(
    preset_id: UUID,
    body: PresetUpdate,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        SubtitlePresetService, Depends(get_subtitle_preset_service)
    ],
    _rate_limit: Annotated[None, Depends(require_subtitle_preset_rate_limit)] = None,
):
    user_id = cast(UUID, user.id)
    return await service.update(
        org_id=org_ctx.org_id,
        user_id=user_id,
        preset_id=preset_id,
        body=body,
    )


@router.delete("/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_preset(
    preset_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        SubtitlePresetService, Depends(get_subtitle_preset_service)
    ],
    _rate_limit: Annotated[None, Depends(require_subtitle_preset_rate_limit)] = None,
):
    user_id = cast(UUID, user.id)
    await service.delete(
        org_id=org_ctx.org_id, user_id=user_id, preset_id=preset_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
