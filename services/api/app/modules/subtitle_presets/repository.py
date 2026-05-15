"""Async CRUD repository for SubtitlePreset.

All queries org-scoped. Owner-only mutations (update / delete) are enforced
by checking ``user_id`` matches before applying the change — non-owners get
``None`` back, which the router translates to 403.

Cross-org isolation: every read passes ``org_id`` in the WHERE; a request
from org A querying for a preset that lives in org B returns nothing,
even when the UUID is known.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import SubtitlePreset
from .schemas import PresetKind


class SubtitlePresetRepository:
    def __init__(self, session: AsyncSession):
        self.session: AsyncSession = session

    async def list_visible(
        self,
        *,
        org_id: UUID,
        user_id: UUID,
        kind: PresetKind | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[SubtitlePreset], int]:
        """Own presets ∪ org-shared presets, optionally filtered by kind.

        Order: created_at DESC. Pagination: limit + offset.
        """
        visibility = and_(
            SubtitlePreset.org_id == org_id,
            or_(
                SubtitlePreset.user_id == user_id,
                SubtitlePreset.is_shared.is_(True),
            ),
        )
        where_clauses = [visibility]
        if kind is not None:
            where_clauses.append(SubtitlePreset.kind == kind)

        count_result = await self.session.execute(
            select(func.count()).select_from(SubtitlePreset).where(*where_clauses)
        )
        total = count_result.scalar_one()

        result = await self.session.execute(
            select(SubtitlePreset)
            .where(*where_clauses)
            .order_by(SubtitlePreset.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        items = list(result.scalars().all())
        return items, total

    async def get_visible(
        self, *, org_id: UUID, user_id: UUID, preset_id: UUID
    ) -> SubtitlePreset | None:
        """Fetch a preset if it's visible to (org, user) — own or shared."""
        result = await self.session.execute(
            select(SubtitlePreset).where(
                SubtitlePreset.id == preset_id,
                SubtitlePreset.org_id == org_id,
                or_(
                    SubtitlePreset.user_id == user_id,
                    SubtitlePreset.is_shared.is_(True),
                ),
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        org_id: UUID,
        user_id: UUID,
        name: str,
        kind: PresetKind,
        style_json: dict[str, Any],
        is_shared: bool,
    ) -> SubtitlePreset:
        preset = SubtitlePreset(
            org_id=org_id,
            user_id=user_id,
            name=name,
            kind=kind,
            style_json=style_json,
            is_shared=is_shared,
        )
        self.session.add(preset)
        await self.session.flush()
        return preset

    async def update_owned(
        self,
        *,
        org_id: UUID,
        user_id: UUID,
        preset_id: UUID,
        name: str | None = None,
        style_json: dict[str, Any] | None = None,
        is_shared: bool | None = None,
    ) -> SubtitlePreset | None:
        """Owner-only update. Returns None if the preset doesn't exist OR if
        the requester is not the creator (visible-but-not-owned shared preset).
        """
        result = await self.session.execute(
            select(SubtitlePreset).where(
                SubtitlePreset.id == preset_id,
                SubtitlePreset.org_id == org_id,
                SubtitlePreset.user_id == user_id,
            )
        )
        preset = result.scalar_one_or_none()
        if preset is None:
            return None
        if name is not None:
            preset.name = name
        if style_json is not None:
            preset.style_json = style_json
        if is_shared is not None:
            preset.is_shared = is_shared
        await self.session.flush()
        return preset

    async def delete_owned(
        self, *, org_id: UUID, user_id: UUID, preset_id: UUID
    ) -> bool:
        """Owner-only delete. Returns False if not found or not owned."""
        result = await self.session.execute(
            select(SubtitlePreset).where(
                SubtitlePreset.id == preset_id,
                SubtitlePreset.org_id == org_id,
                SubtitlePreset.user_id == user_id,
            )
        )
        preset = result.scalar_one_or_none()
        if preset is None:
            return False
        await self.session.delete(preset)
        await self.session.flush()
        return True
