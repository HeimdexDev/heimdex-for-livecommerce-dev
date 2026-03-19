from typing import TypedDict, cast, final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.drive.models import DriveWatchedFolder


@final
class WatchedFolderRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_org(self, org_id: UUID) -> list[DriveWatchedFolder]:
        result = await self.session.execute(
            select(DriveWatchedFolder)
            .where(DriveWatchedFolder.org_id == org_id)
            .order_by(DriveWatchedFolder.folder_path.asc())
        )
        return list(result.scalars().all())

    async def list_enabled(self, org_id: UUID) -> list[DriveWatchedFolder]:
        result = await self.session.execute(
            select(DriveWatchedFolder)
            .where(
                DriveWatchedFolder.org_id == org_id,
                DriveWatchedFolder.sync_enabled.is_(True),
            )
            .order_by(DriveWatchedFolder.folder_path.asc())
        )
        return list(result.scalars().all())

    async def list_by_connection(self, connection_id: UUID) -> list[DriveWatchedFolder]:
        result = await self.session.execute(
            select(DriveWatchedFolder)
            .where(DriveWatchedFolder.connection_id == connection_id)
            .order_by(DriveWatchedFolder.folder_path.asc())
        )
        return list(result.scalars().all())

    async def list_enabled_by_connection(self, connection_id: UUID) -> list[DriveWatchedFolder]:
        result = await self.session.execute(
            select(DriveWatchedFolder)
            .where(
                DriveWatchedFolder.connection_id == connection_id,
                DriveWatchedFolder.sync_enabled.is_(True),
            )
            .order_by(DriveWatchedFolder.folder_path.asc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, folder_id: UUID, org_id: UUID) -> DriveWatchedFolder | None:
        result = await self.session.execute(
            select(DriveWatchedFolder).where(
                DriveWatchedFolder.id == folder_id,
                DriveWatchedFolder.org_id == org_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_google_folder_id(
        self,
        org_id: UUID,
        google_folder_id: str,
    ) -> DriveWatchedFolder | None:
        result = await self.session.execute(
            select(DriveWatchedFolder).where(
                DriveWatchedFolder.org_id == org_id,
                DriveWatchedFolder.google_folder_id == google_folder_id,
            )
        )
        return result.scalar_one_or_none()

    async def bulk_upsert(
        self,
        org_id: UUID,
        connection_id: UUID,
        folders: list["WatchedFolderInput"],
    ) -> dict[str, int]:
        if not folders:
            return {"created": 0, "updated": 0}

        deduped: dict[str, WatchedFolderUpsertRow] = {}
        for folder in folders:
            google_folder_id = folder["google_folder_id"]
            deduped[google_folder_id] = {
                "org_id": org_id,
                "connection_id": connection_id,
                "google_folder_id": google_folder_id,
                "folder_name": folder["folder_name"],
                "folder_path": folder.get("folder_path"),
                "parent_folder_id": folder.get("parent_folder_id"),
                "last_enumerated_at": func.now(),
            }

        google_folder_ids = list(deduped.keys())
        existing_result = await self.session.execute(
            select(DriveWatchedFolder.google_folder_id).where(
                DriveWatchedFolder.org_id == org_id,
                DriveWatchedFolder.google_folder_id.in_(google_folder_ids),
            )
        )
        existing_ids = set(existing_result.scalars().all())

        insert_stmt = pg_insert(DriveWatchedFolder).values(list(deduped.values()))
        _ = await self.session.execute(
            insert_stmt.on_conflict_do_update(
                constraint="uq_watched_folders_org_folder",
                set_={
                    "folder_name": insert_stmt.excluded.folder_name,
                    "folder_path": insert_stmt.excluded.folder_path,
                    "parent_folder_id": insert_stmt.excluded.parent_folder_id,
                    "last_enumerated_at": func.now(),
                },
            )
        )
        await self.session.flush()

        updated = len(existing_ids)
        created = len(google_folder_ids) - updated
        return {"created": created, "updated": updated}

    async def update_toggle(
        self,
        folder_id: UUID,
        org_id: UUID,
        sync_enabled: bool,
    ) -> DriveWatchedFolder | None:
        _ = await self.session.execute(
            update(DriveWatchedFolder)
            .where(
                DriveWatchedFolder.id == folder_id,
                DriveWatchedFolder.org_id == org_id,
            )
            .values(sync_enabled=sync_enabled)
        )
        await self.session.flush()
        return await self.get_by_id(folder_id, org_id)

    async def update_content_types(
        self,
        folder_id: UUID,
        org_id: UUID,
        content_types: list[str],
    ) -> DriveWatchedFolder | None:
        _ = await self.session.execute(
            update(DriveWatchedFolder)
            .where(
                DriveWatchedFolder.id == folder_id,
                DriveWatchedFolder.org_id == org_id,
            )
            .values(content_types=content_types)
        )
        await self.session.flush()
        return await self.get_by_id(folder_id, org_id)

    async def get_enabled_folder_ids(self, connection_id: UUID) -> set[str]:
        result = await self.session.execute(
            select(DriveWatchedFolder.google_folder_id).where(
                DriveWatchedFolder.connection_id == connection_id,
                DriveWatchedFolder.sync_enabled.is_(True),
            )
        )
        return set(result.scalars().all())

    async def get_enabled_folder_map(self, connection_id: UUID) -> dict[str, list[str]]:
        result = await self.session.execute(
            select(DriveWatchedFolder.google_folder_id, DriveWatchedFolder.content_types).where(
                DriveWatchedFolder.connection_id == connection_id,
                DriveWatchedFolder.sync_enabled.is_(True),
            )
        )
        rows = cast(list[tuple[str, list[str]]], result.all())
        return {
            str(row[0]): list(row[1])
            for row in rows
        }

    async def update_file_counts(self, org_id: UUID, counts: dict[str, int]) -> None:
        if not counts:
            return

        _ = await self.session.execute(
            update(DriveWatchedFolder)
            .where(
                DriveWatchedFolder.org_id == org_id,
                DriveWatchedFolder.google_folder_id.in_(list(counts.keys())),
            )
            .values(
                file_count_cached=sa.case(
                    counts,
                    value=DriveWatchedFolder.google_folder_id,
                    else_=DriveWatchedFolder.file_count_cached,
                )
            )
        )
        await self.session.flush()


class WatchedFolderInput(TypedDict):
    google_folder_id: str
    folder_name: str
    folder_path: str | None
    parent_folder_id: str | None


class WatchedFolderUpsertRow(TypedDict):
    org_id: UUID
    connection_id: UUID
    google_folder_id: str
    folder_name: str
    folder_path: str | None
    parent_folder_id: str | None
    last_enumerated_at: object
