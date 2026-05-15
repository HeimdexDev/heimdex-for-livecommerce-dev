"""Service layer for subtitle presets.

Thin wrapper over the repository — converts ORM rows to response schemas
with the per-request ``is_owned`` flag computed from the requesting user.
The router is intentionally kept skinny; if business logic grows (preset
quotas, audit events), it lands here, not in the router.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from .models import SubtitlePreset
from .repository import SubtitlePresetRepository
from .schemas import (
    PresetCreate,
    PresetKind,
    PresetListResponse,
    PresetResponse,
    PresetUpdate,
)


def _to_response(preset: SubtitlePreset, *, requesting_user_id: UUID) -> PresetResponse:
    return PresetResponse(
        id=preset.id,
        org_id=preset.org_id,
        user_id=preset.user_id,
        name=preset.name,
        kind=preset.kind,  # pyright: ignore[reportArgumentType] — DB stores as str, schema is Literal
        style_json=preset.style_json,
        is_shared=preset.is_shared,
        is_owned=(preset.user_id == requesting_user_id),
        created_at=preset.created_at,
        updated_at=preset.updated_at,
    )


class SubtitlePresetService:
    def __init__(self, repo: SubtitlePresetRepository):
        self.repo: SubtitlePresetRepository = repo

    async def list(
        self,
        *,
        org_id: UUID,
        user_id: UUID,
        kind: PresetKind | None,
        limit: int,
        offset: int,
    ) -> PresetListResponse:
        items, total = await self.repo.list_visible(
            org_id=org_id, user_id=user_id, kind=kind, limit=limit, offset=offset
        )
        return PresetListResponse(
            items=[_to_response(p, requesting_user_id=user_id) for p in items],
            total=total,
        )

    async def create(
        self, *, org_id: UUID, user_id: UUID, body: PresetCreate
    ) -> PresetResponse:
        preset = await self.repo.create(
            org_id=org_id,
            user_id=user_id,
            name=body.name,
            kind=body.kind,
            style_json=body.style_json,
            is_shared=body.is_shared,
        )
        return _to_response(preset, requesting_user_id=user_id)

    async def update(
        self,
        *,
        org_id: UUID,
        user_id: UUID,
        preset_id: UUID,
        body: PresetUpdate,
    ) -> PresetResponse:
        # Need the existing preset's kind to validate style_json against the
        # right contract type. Fetch via visible-scope first; if it exists but
        # we're not owner, fall through to update_owned which will return None
        # and we'll raise 403.
        existing = await self.repo.get_visible(
            org_id=org_id, user_id=user_id, preset_id=preset_id
        )
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Preset not found",
            )
        validated_style: dict[str, Any] | None = body.validated_style_json(
            existing.kind  # pyright: ignore[reportArgumentType]
        )

        updated = await self.repo.update_owned(
            org_id=org_id,
            user_id=user_id,
            preset_id=preset_id,
            name=body.name,
            style_json=validated_style,
            is_shared=body.is_shared,
        )
        if updated is None:
            # Visible (above check passed) but not owned — shared preset from
            # another user. 403 is correct: caller exists in the scope but
            # lacks permission to mutate.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the preset owner can modify this preset",
            )
        return _to_response(updated, requesting_user_id=user_id)

    async def delete(
        self, *, org_id: UUID, user_id: UUID, preset_id: UUID
    ) -> None:
        existing = await self.repo.get_visible(
            org_id=org_id, user_id=user_id, preset_id=preset_id
        )
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Preset not found",
            )
        deleted = await self.repo.delete_owned(
            org_id=org_id, user_id=user_id, preset_id=preset_id
        )
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the preset owner can delete this preset",
            )
