from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.libraries.models import Library


class LibraryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, library_id: UUID, org_id: UUID) -> Library | None:
        result = await self.session.execute(
            select(Library).where(Library.id == library_id, Library.org_id == org_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self, org_id: UUID, name: str, created_by_user_id: UUID | None = None
    ) -> Library:
        library = Library(org_id=org_id, name=name, created_by_user_id=created_by_user_id)
        self.session.add(library)
        await self.session.flush()
        return library

    async def get_by_name(self, org_id: UUID, name: str) -> Library | None:
        result = await self.session.execute(
            select(Library).where(Library.org_id == org_id, Library.name == name)
        )
        return result.scalar_one_or_none()

    async def list_by_org(self, org_id: UUID, limit: int = 200) -> list[Library]:
        result = await self.session.execute(
            select(Library).where(Library.org_id == org_id).order_by(Library.name).limit(limit)
        )
        return list(result.scalars().all())
