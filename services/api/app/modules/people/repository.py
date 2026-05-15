from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.people.models import (
    DriveNicknameRegistry,
    PeopleClusterLabel,
    PeopleExcludePreference,
    PeopleVideoExclusion,
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

    async def search_by_label(
        self, org_id: UUID, query: str, limit: int = 500,
    ) -> list[str]:
        result = await self.session.execute(
            select(PeopleClusterLabel.person_cluster_id).where(
                PeopleClusterLabel.org_id == org_id,
                PeopleClusterLabel.label.isnot(None),
                PeopleClusterLabel.label.ilike(f"%{query}%"),
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

    async def merge_labels(
        self,
        org_id: UUID,
        source_cluster_id: str,
        target_cluster_id: str,
        keep_label: str | None = None,
    ) -> None:
        """Merge source cluster label into target.

        If keep_label is provided, it overrides the target label.
        Otherwise the target keeps its existing label (or inherits source label
        if target has no label).
        Deletes the source cluster label row.
        """
        source = await self.get_by_cluster_id(org_id, source_cluster_id)
        target = await self.get_by_cluster_id(org_id, target_cluster_id)

        # Determine the label to use
        if keep_label is not None:
            resolved_label = keep_label if keep_label else None
        elif target and target.label:
            resolved_label = target.label
        elif source and source.label:
            resolved_label = source.label
        else:
            resolved_label = None

        # Ensure target row exists with the resolved label
        if target is None:
            await self.set_label(org_id, target_cluster_id, resolved_label)
        elif target.label != resolved_label:
            target.label = resolved_label
            await self.session.flush()

        # Delete source row
        if source is not None:
            await self.session.delete(source)
            await self.session.flush()

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
        result_obj: object = await self.session.execute(
            delete(PeopleExcludePreference).where(
                PeopleExcludePreference.org_id == org_id,
                PeopleExcludePreference.person_cluster_id == cluster_id,
            )
        )
        await self.session.flush()
        rowcount = getattr(result_obj, "rowcount", 0)
        return int(rowcount or 0)

    async def transfer_exclusions(
        self,
        org_id: UUID,
        source_cluster_id: str,
        target_cluster_id: str,
    ) -> int:
        """Transfer exclude preferences from source cluster to target.

        For each user who had the source cluster excluded:
        - If they don't already exclude the target, update the row in-place
        - If they already exclude the target, delete the duplicate source row

        Returns the number of rows affected.
        """
        # Find all users who exclude the source
        source_prefs = await self.session.execute(
            select(PeopleExcludePreference).where(
                PeopleExcludePreference.org_id == org_id,
                PeopleExcludePreference.person_cluster_id == source_cluster_id,
            )
        )
        source_rows = list(source_prefs.scalars().all())

        if not source_rows:
            return 0

        # Find which users already exclude the target
        target_prefs = await self.session.execute(
            select(PeopleExcludePreference.user_id).where(
                PeopleExcludePreference.org_id == org_id,
                PeopleExcludePreference.person_cluster_id == target_cluster_id,
            )
        )
        users_with_target = set(target_prefs.scalars().all())

        affected = 0
        for row in source_rows:
            if row.user_id in users_with_target:
                # User already excludes target — just delete the source row
                await self.session.delete(row)
            else:
                # Transfer: update source row to point to target
                row.person_cluster_id = target_cluster_id
            affected += 1

        await self.session.flush()
        return affected


class PeopleVideoExclusionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_user_and_person(
        self, org_id: UUID, user_id: UUID, person_cluster_id: str,
    ) -> list[str]:
        """Return excluded video_ids for a specific user+person pair."""
        result = await self.session.execute(
            select(PeopleVideoExclusion.video_id).where(
                PeopleVideoExclusion.org_id == org_id,
                PeopleVideoExclusion.user_id == user_id,
                PeopleVideoExclusion.person_cluster_id == person_cluster_id,
            )
        )
        return list(result.scalars().all())

    async def list_by_user(
        self, org_id: UUID, user_id: UUID, limit: int = 2000,
    ) -> list[tuple[str, str]]:
        """Return all (person_cluster_id, video_id) pairs for a user.
        Used at search time to build compound must_not clauses."""
        result = await self.session.execute(
            select(
                PeopleVideoExclusion.person_cluster_id,
                PeopleVideoExclusion.video_id,
            ).where(
                PeopleVideoExclusion.org_id == org_id,
                PeopleVideoExclusion.user_id == user_id,
            ).limit(limit)
        )
        return list(result.tuples().all())

    async def replace_for_person(
        self, org_id: UUID, user_id: UUID, person_cluster_id: str,
        excluded_video_ids: list[str],
    ) -> list[str]:
        """Atomically replace all video exclusions for one user+person."""
        await self.session.execute(
            delete(PeopleVideoExclusion).where(
                PeopleVideoExclusion.org_id == org_id,
                PeopleVideoExclusion.user_id == user_id,
                PeopleVideoExclusion.person_cluster_id == person_cluster_id,
            )
        )
        for vid in excluded_video_ids:
            self.session.add(
                PeopleVideoExclusion(
                    org_id=org_id,
                    user_id=user_id,
                    person_cluster_id=person_cluster_id,
                    video_id=vid,
                )
            )
        await self.session.flush()
        return excluded_video_ids

    async def delete_by_cluster_id(self, org_id: UUID, cluster_id: str) -> int:
        """Delete ALL video exclusions for a cluster (all users, all videos).
        Called during person delete."""
        result_obj: object = await self.session.execute(
            delete(PeopleVideoExclusion).where(
                PeopleVideoExclusion.org_id == org_id,
                PeopleVideoExclusion.person_cluster_id == cluster_id,
            )
        )
        await self.session.flush()
        rowcount = getattr(result_obj, "rowcount", 0)
        return int(rowcount or 0)

    async def transfer_exclusions(
        self, org_id: UUID, source_cluster_id: str, target_cluster_id: str,
    ) -> int:
        """Transfer video exclusions from source -> target during merge.
        Deduplicates: if user already excludes (target, video), deletes source row."""
        source_prefs = await self.session.execute(
            select(PeopleVideoExclusion).where(
                PeopleVideoExclusion.org_id == org_id,
                PeopleVideoExclusion.person_cluster_id == source_cluster_id,
            )
        )
        source_rows = list(source_prefs.scalars().all())
        if not source_rows:
            return 0

        # Find existing (user_id, video_id) pairs for target
        target_prefs = await self.session.execute(
            select(
                PeopleVideoExclusion.user_id,
                PeopleVideoExclusion.video_id,
            ).where(
                PeopleVideoExclusion.org_id == org_id,
                PeopleVideoExclusion.person_cluster_id == target_cluster_id,
            )
        )
        existing_target = set(target_prefs.tuples().all())

        affected = 0
        for row in source_rows:
            if (row.user_id, row.video_id) in existing_target:
                await self.session.delete(row)
            else:
                row.person_cluster_id = target_cluster_id
            affected += 1
        await self.session.flush()
        return affected
