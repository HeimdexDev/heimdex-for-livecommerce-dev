"""Async CRUD repository for TextTemplate.

Org-scoped queries enforce multi-tenant isolation.
System presets (is_system_preset=True) are read-only.
"""

from uuid import UUID

from sqlalchemy import case, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import TextTemplate
from .schemas import TextTemplateCreate, TextTemplateUpdate


class TextTemplateRepository:
    def __init__(self, session: AsyncSession):
        self.session: AsyncSession = session

    async def create(
        self,
        org_id: UUID,
        user_id: UUID,
        data: TextTemplateCreate,
    ) -> TextTemplate:
        template = TextTemplate(
            org_id=org_id,
            user_id=user_id,
            **data.model_dump(),
        )
        self.session.add(template)
        await self.session.flush()
        return template

    async def get_by_id(self, org_id: UUID, template_id: UUID) -> TextTemplate | None:
        result = await self.session.execute(
            select(TextTemplate).where(
                TextTemplate.id == template_id,
                TextTemplate.org_id == org_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        org_id: UUID,
        user_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[TextTemplate], int]:
        """Returns user's templates + system presets. System presets first."""
        where = (
            TextTemplate.org_id == org_id,
            or_(
                TextTemplate.user_id == user_id,
                TextTemplate.is_system_preset.is_(True),
            ),
        )

        count_result = await self.session.execute(
            select(func.count()).select_from(TextTemplate).where(*where)
        )
        total = count_result.scalar_one()

        result = await self.session.execute(
            select(TextTemplate)
            .where(*where)
            .order_by(
                TextTemplate.is_system_preset.desc(),
                TextTemplate.created_at.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        templates = list(result.scalars().all())
        return templates, total

    async def update(
        self,
        org_id: UUID,
        template_id: UUID,
        data: TextTemplateUpdate,
    ) -> TextTemplate | None:
        """Update a user-owned template. Returns None for system presets or not found."""
        template = await self.get_by_id(org_id, template_id)
        if template is None or template.is_system_preset:
            return None

        update_data = data.model_dump(exclude_unset=True)
        if not update_data:
            return template

        for key, value in update_data.items():
            setattr(template, key, value)
        await self.session.flush()
        return template

    async def delete(self, org_id: UUID, template_id: UUID) -> bool:
        """Delete a user-owned template. Returns False for system presets or not found."""
        template = await self.get_by_id(org_id, template_id)
        if template is None or template.is_system_preset:
            return False
        await self.session.delete(template)
        await self.session.flush()
        return True
