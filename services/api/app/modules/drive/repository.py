from typing import Optional
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.drive.models import DriveConnection, DriveFile, DriveSecret
from app.modules.drive.schemas import DriveConnectionCreate, DriveConnectionUpdate


class DriveConnectionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_org(self, org_id: UUID) -> list[DriveConnection]:
        result = await self.session.execute(
            select(DriveConnection)
            .where(DriveConnection.org_id == org_id)
            .order_by(DriveConnection.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, connection_id: UUID, org_id: UUID) -> Optional[DriveConnection]:
        result = await self.session.execute(
            select(DriveConnection).where(
                DriveConnection.id == connection_id,
                DriveConnection.org_id == org_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, org_id: UUID, body: DriveConnectionCreate) -> DriveConnection:
        conn = DriveConnection(
            org_id=org_id,
            library_id=body.library_id,
            drive_id=body.drive_id,
            drive_name=body.drive_name,
        )
        self.session.add(conn)
        await self.session.flush()
        await self.session.refresh(conn)
        return conn

    async def update(
        self, connection_id: UUID, org_id: UUID, body: DriveConnectionUpdate
    ) -> Optional[DriveConnection]:
        conn = await self.get_by_id(connection_id, org_id)
        if conn is None:
            return None
        update_data = body.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(conn, key, value)
        await self.session.flush()
        await self.session.refresh(conn)
        return conn

    async def delete(self, connection_id: UUID, org_id: UUID) -> bool:
        conn = await self.get_by_id(connection_id, org_id)
        if conn is None:
            return False
        await self.session.delete(conn)
        await self.session.flush()
        return True

    async def get_active_connections(self) -> list[DriveConnection]:
        result = await self.session.execute(
            select(DriveConnection).where(DriveConnection.status == "active")
        )
        return list(result.scalars().all())


class DriveFileRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, file_id: UUID, org_id: UUID) -> Optional[DriveFile]:
        result = await self.session.execute(
            select(DriveFile).where(
                DriveFile.id == file_id,
                DriveFile.org_id == org_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_google_file_id(self, org_id: UUID, google_file_id: str) -> Optional[DriveFile]:
        result = await self.session.execute(
            select(DriveFile).where(
                DriveFile.org_id == org_id,
                DriveFile.google_file_id == google_file_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_connection(
        self,
        connection_id: UUID,
        org_id: UUID,
        processing_status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[DriveFile], int]:
        base = select(DriveFile).where(
            DriveFile.connection_id == connection_id,
            DriveFile.org_id == org_id,
            DriveFile.is_deleted.is_(False),
        )
        count_q = select(func.count()).select_from(base.subquery())

        if processing_status:
            base = base.where(DriveFile.processing_status == processing_status)
            count_q = select(func.count()).select_from(base.subquery())

        result = await self.session.execute(
            base.order_by(DriveFile.created_at.desc()).limit(limit).offset(offset)
        )
        count_result = await self.session.execute(count_q)
        return list(result.scalars().all()), count_result.scalar_one()

    async def create(self, drive_file: DriveFile) -> DriveFile:
        self.session.add(drive_file)
        await self.session.flush()
        await self.session.refresh(drive_file)
        return drive_file

    async def claim_pending_files(
        self,
        org_id: UUID,
        limit: int = 1,
    ) -> list[DriveFile]:
        """Atomically claim pending files for processing using SELECT FOR UPDATE SKIP LOCKED."""
        result = await self.session.execute(
            select(DriveFile)
            .where(
                DriveFile.org_id == org_id,
                DriveFile.processing_status == "pending",
                DriveFile.is_deleted.is_(False),
                DriveFile.retry_count < DriveFile.max_retries,
            )
            .order_by(DriveFile.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        files = list(result.scalars().all())
        for f in files:
            f.processing_status = "downloading"
        if files:
            await self.session.flush()
        return files

    async def update_status(
        self,
        file_id: UUID,
        status: str,
        error: Optional[str] = None,
        **extra_fields: object,
    ) -> None:
        values: dict[str, object] = {"processing_status": status}
        if error is not None:
            values["last_error"] = error
        values.update(extra_fields)
        await self.session.execute(
            update(DriveFile).where(DriveFile.id == file_id).values(**values)
        )
        await self.session.flush()

    async def increment_retry(self, file_id: UUID, error: str) -> None:
        await self.session.execute(
            update(DriveFile)
            .where(DriveFile.id == file_id)
            .values(
                retry_count=DriveFile.retry_count + 1,
                last_error=error,
                processing_status="pending",
                last_attempt_at=func.now(),
            )
        )
        await self.session.flush()

    async def mark_failed(self, file_id: UUID, error: str) -> None:
        await self.session.execute(
            update(DriveFile)
            .where(DriveFile.id == file_id)
            .values(
                processing_status="failed",
                last_error=error,
                last_attempt_at=func.now(),
            )
        )
        await self.session.flush()


class DriveSecretRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_org(self, org_id: UUID) -> Optional[DriveSecret]:
        result = await self.session.execute(
            select(DriveSecret).where(DriveSecret.org_id == org_id)
        )
        return result.scalar_one_or_none()

    async def upsert(self, org_id: UUID, encrypted_value: bytes, nonce: bytes, impersonate_email: str) -> DriveSecret:
        existing = await self.get_by_org(org_id)
        if existing:
            existing.encrypted_value = encrypted_value
            existing.nonce = nonce
            existing.impersonate_email = impersonate_email
            await self.session.flush()
            await self.session.refresh(existing)
            return existing
        secret = DriveSecret(
            org_id=org_id,
            encrypted_value=encrypted_value,
            nonce=nonce,
            impersonate_email=impersonate_email,
        )
        self.session.add(secret)
        await self.session.flush()
        await self.session.refresh(secret)
        return secret
