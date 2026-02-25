from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.people.models import (
    DriveNicknameRegistry,
    PeopleClusterLabel,
    PeopleExcludePreference,
)


class DriveNicknameRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_fingerprint(
        self, org_id: UUID, fingerprint_hash: str
    ) -> DriveNicknameRegistry | None:
        result = await self.session.execute(
            select(DriveNicknameRegistry).where(
                DriveNicknameRegistry.org_id == org_id,
                DriveNicknameRegistry.source_fingerprint_hash == fingerprint_hash,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self, org_id: UUID, fingerprint_hash: str, nickname: str
    ) -> DriveNicknameRegistry:
        existing = await self.get_by_fingerprint(org_id, fingerprint_hash)
        if existing:
            existing.nickname = nickname
            existing.last_seen_at = datetime.now(timezone.utc)
            await self.session.flush()
            return existing
        
        entry = DriveNicknameRegistry(
            org_id=org_id, source_fingerprint_hash=fingerprint_hash, nickname=nickname
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def list_by_org(self, org_id: UUID, limit: int = 500) -> list[DriveNicknameRegistry]:
        result = await self.session.execute(
            select(DriveNicknameRegistry)
            .where(DriveNicknameRegistry.org_id == org_id)
            .limit(limit)
        )
        return list(result.scalars().all())


class PeopleClusterLabelRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_cluster_id(
        self, org_id: UUID, cluster_id: str
    ) -> PeopleClusterLabel | None:
        result = await self.session.execute(
            select(PeopleClusterLabel).where(
                PeopleClusterLabel.org_id == org_id,
                PeopleClusterLabel.person_cluster_id == cluster_id,
            )
        )
        return result.scalar_one_or_none()

    async def set_label(
        self, org_id: UUID, cluster_id: str, label: str | None
    ) -> PeopleClusterLabel:
        existing = await self.get_by_cluster_id(org_id, cluster_id)
        if existing:
            existing.label = label
            await self.session.flush()
            return existing
        
        entry = PeopleClusterLabel(
            org_id=org_id, person_cluster_id=cluster_id, label=label
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def list_by_org(self, org_id: UUID, limit: int = 500) -> list[PeopleClusterLabel]:
        result = await self.session.execute(
            select(PeopleClusterLabel)
            .where(PeopleClusterLabel.org_id == org_id)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_labeled(self, org_id: UUID, limit: int = 500) -> list[PeopleClusterLabel]:
        result = await self.session.execute(
            select(PeopleClusterLabel).where(
                PeopleClusterLabel.org_id == org_id,
                PeopleClusterLabel.label.isnot(None),
            ).limit(limit)
        )
        return list(result.scalars().all())

    async def delete_by_cluster_id(self, org_id: UUID, cluster_id: str) -> bool:
        """Hard-delete a cluster label row. Returns True if a row was deleted."""
        existing = await self.get_by_cluster_id(org_id, cluster_id)
        if existing is None:
            return False
        await self.session.delete(existing)
        await self.session.flush()
        return True


class PeopleExcludePreferenceRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_user(self, org_id: UUID, user_id: UUID, limit: int = 500) -> list[str]:
        result = await self.session.execute(
            select(PeopleExcludePreference.person_cluster_id).where(
                PeopleExcludePreference.org_id == org_id,
                PeopleExcludePreference.user_id == user_id,
            ).limit(limit)
        )
        return list(result.scalars().all())

    async def replace_all(
        self, org_id: UUID, user_id: UUID, person_cluster_ids: list[str]
    ) -> list[str]:
        await self.session.execute(
            delete(PeopleExcludePreference).where(
                PeopleExcludePreference.org_id == org_id,
                PeopleExcludePreference.user_id == user_id,
            )
        )
        for cluster_id in person_cluster_ids:
            self.session.add(
                PeopleExcludePreference(
                    org_id=org_id,
                    user_id=user_id,
                    person_cluster_id=cluster_id,
                )
            )
        await self.session.flush()
        return person_cluster_ids

    async def delete_by_cluster_id(self, org_id: UUID, cluster_id: str) -> int:
        """Delete all exclude preferences for a cluster across all users.

        Returns the number of rows deleted.
        """
        result = await self.session.execute(
            delete(PeopleExcludePreference).where(
                PeopleExcludePreference.org_id == org_id,
                PeopleExcludePreference.person_cluster_id == cluster_id,
            )
        )
        await self.session.flush()
        return result.rowcount  # type: ignore[return-value]
