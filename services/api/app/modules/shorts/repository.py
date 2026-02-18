from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.shorts.models import SavedShort


class SavedShortRepository:
    def __init__(self, session: AsyncSession):
        self.session: AsyncSession = session

    async def create(
        self,
        *,
        org_id: UUID,
        user_id: UUID,
        video_id: str,
        scene_ids: list[str],
        title: str | None,
        start_ms: int | None,
        end_ms: int | None,
    ) -> SavedShort:
        short = SavedShort(
            org_id=org_id,
            user_id=user_id,
            video_id=video_id,
            scene_ids=scene_ids,
            title=title,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        self.session.add(short)
        await self.session.flush()
        return short

    async def list_by_user(self, org_id: UUID, user_id: UUID) -> list[SavedShort]:
        result = await self.session.execute(
            select(SavedShort)
            .where(
                SavedShort.org_id == org_id,
                SavedShort.user_id == user_id,
            )
            .order_by(SavedShort.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, short_id: UUID, org_id: UUID) -> SavedShort | None:
        result = await self.session.execute(
            select(SavedShort).where(
                SavedShort.id == short_id,
                SavedShort.org_id == org_id,
            )
        )
        return result.scalar_one_or_none()

    async def delete(self, short: SavedShort) -> None:
        await self.session.delete(short)
        await self.session.flush()
