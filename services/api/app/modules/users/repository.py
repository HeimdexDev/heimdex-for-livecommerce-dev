from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import User, UserRole


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, user_id: UUID, org_id: UUID) -> User | None:
        result = await self.session.execute(
            select(User).where(User.id == user_id, User.org_id == org_id)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str, org_id: UUID) -> User | None:
        result = await self.session.execute(
            select(User).where(User.email == email, User.org_id == org_id)
        )
        return result.scalar_one_or_none()

    async def create(self, org_id: UUID, email: str, role: UserRole = UserRole.MEMBER) -> User:
        user = User(org_id=org_id, email=email, role=role)
        self.session.add(user)
        await self.session.flush()
        return user

    async def list_by_org(self, org_id: UUID, limit: int = 500) -> list[User]:
        result = await self.session.execute(
            select(User).where(User.org_id == org_id).limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_auth0_sub(self, auth0_sub: str, org_id: UUID) -> User | None:
        result = await self.session.execute(
            select(User).where(User.auth0_sub == auth0_sub, User.org_id == org_id)
        )
        return result.scalar_one_or_none()

    async def link_auth0_sub(self, user_id: UUID, auth0_sub: str) -> None:
        result = await self.session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            user.auth0_sub = auth0_sub
            await self.session.flush()
