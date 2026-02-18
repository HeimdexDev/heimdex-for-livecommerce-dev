from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db_session
from app.modules.auth.service import get_current_user
from app.modules.shorts.models import SavedShort
from app.modules.shorts.repository import SavedShortRepository
from app.modules.shorts.schemas import (
    SavedShortCreate,
    SavedShortResponse,
    SavedShortsListResponse,
)
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org
from app.modules.users.models import User

router = APIRouter(prefix="/shorts", tags=["shorts"])


def _to_response(short: SavedShort) -> SavedShortResponse:
    return SavedShortResponse(
        id=cast(UUID, short.id),
        video_id=short.video_id,
        scene_ids=short.scene_ids,
        title=short.title,
        start_ms=short.start_ms,
        end_ms=short.end_ms,
        created_at=short.created_at,
    )


@router.post("", response_model=SavedShortResponse, status_code=status.HTTP_201_CREATED)
async def create_saved_short(
    body: SavedShortCreate,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    repo = SavedShortRepository(db)
    user_id = cast(UUID, user.id)
    short = await repo.create(
        org_id=org_ctx.org_id,
        user_id=user_id,
        video_id=body.video_id,
        scene_ids=body.scene_ids,
        title=body.title,
        start_ms=body.start_ms,
        end_ms=body.end_ms,
    )
    return _to_response(short)


@router.get("", response_model=SavedShortsListResponse)
async def list_saved_shorts(
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    repo = SavedShortRepository(db)
    user_id = cast(UUID, user.id)
    shorts = await repo.list_by_user(org_ctx.org_id, user_id)
    return SavedShortsListResponse(
        shorts=[_to_response(short) for short in shorts],
        total=len(shorts),
    )


@router.delete("/{short_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_short(
    short_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    repo = SavedShortRepository(db)
    user_id = cast(UUID, user.id)
    short = await repo.get_by_id(short_id, org_ctx.org_id)
    if short is None or short.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved short not found",
        )

    await repo.delete(short)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
