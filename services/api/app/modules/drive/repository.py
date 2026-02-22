from datetime import datetime
from typing import Optional
from uuid import UUID

import sqlalchemy as sa
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

    async def get_by_video_id(self, org_id: UUID, video_id: str) -> Optional[DriveFile]:
        result = await self.session.execute(
            select(DriveFile).where(
                DriveFile.org_id == org_id,
                DriveFile.video_id == video_id,
                DriveFile.is_deleted.is_(False),
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

    async def count_by_status(self, org_id: UUID) -> dict[str, int]:
        """Return {processing_status: count} for non-deleted files in this org."""
        result = await self.session.execute(
            select(DriveFile.processing_status, func.count())
            .where(DriveFile.org_id == org_id, DriveFile.is_deleted.is_(False))
            .group_by(DriveFile.processing_status)
        )
        rows = result.fetchall()
        return {str(r[0]): int(r[1]) for r in rows}

    async def latest_indexed_at(self, org_id: UUID) -> Optional[datetime]:
        """Return the most recent updated_at among indexed files for this org."""
        result = await self.session.execute(
            select(func.max(DriveFile.updated_at))
            .where(
                DriveFile.org_id == org_id,
                DriveFile.processing_status == "indexed",
                DriveFile.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

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

    async def update_heartbeat(self, file_id: UUID) -> int:
        result = await self.session.execute(
            update(DriveFile)
            .where(DriveFile.id == file_id)
            .values(last_heartbeat_at=func.now())
            .returning(DriveFile.id)
        )
        await self.session.flush()
        return len(list(result.scalars().all()))

    async def reap_stuck_files(self, stale_threshold_minutes: int = 30) -> int:
        threshold_minutes = int(stale_threshold_minutes)
        stale_interval = sa.text(f"INTERVAL '{threshold_minutes} minutes'")
        stale_error = f"Reaped: no heartbeat for {threshold_minutes}min"
        stale_condition = DriveFile.last_heartbeat_at < (func.now() - stale_interval)

        processing_result = await self.session.execute(
            update(DriveFile)
            .where(
                DriveFile.processing_status.in_(
                    ["downloading", "transcoding", "processing", "indexing"]
                ),
                stale_condition,
                DriveFile.retry_count < DriveFile.max_retries,
                DriveFile.is_deleted.is_(False),
            )
            .values(
                processing_status="pending",
                retry_count=DriveFile.retry_count + 1,
                last_error=stale_error,
                last_heartbeat_at=None,
            )
            .returning(DriveFile.id)
        )

        reaped_ids: set[UUID] = set(processing_result.scalars().all())

        stt_result = await self.session.execute(
            update(DriveFile)
            .where(
                DriveFile.stt_status == "running",
                stale_condition,
                DriveFile.is_deleted.is_(False),
            )
            .values(
                stt_status="pending",
                enrichment_state="pending",
                last_heartbeat_at=None,
            )
            .returning(DriveFile.id)
        )
        reaped_ids.update(stt_result.scalars().all())

        ocr_result = await self.session.execute(
            update(DriveFile)
            .where(
                DriveFile.ocr_status == "running",
                stale_condition,
                DriveFile.is_deleted.is_(False),
            )
            .values(
                ocr_status="pending",
                enrichment_state="pending",
                last_heartbeat_at=None,
            )
            .returning(DriveFile.id)
        )
        reaped_ids.update(ocr_result.scalars().all())

        caption_result = await self.session.execute(
            update(DriveFile)
            .where(
                DriveFile.caption_status == "running",
                stale_condition,
                DriveFile.is_deleted.is_(False),
            )
            .values(
                caption_status="pending",
                enrichment_state="pending",
                last_heartbeat_at=None,
            )
            .returning(DriveFile.id)
        )
        reaped_ids.update(caption_result.scalars().all())

        await self.session.flush()
        return len(reaped_ids)


    async def claim_stt_pending_files(self, limit: int = 1) -> list[DriveFile]:
        """Claim files ready for STT enrichment using SELECT FOR UPDATE SKIP LOCKED."""
        result = await self.session.execute(
            select(DriveFile)
            .where(
                DriveFile.enrichment_state.in_(["pending", "failed_partial"]),
                DriveFile.stt_status == "pending",
                DriveFile.audio_s3_key.isnot(None),
                DriveFile.is_deleted.is_(False),
            )
            .order_by(DriveFile.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        files = list(result.scalars().all())
        for f in files:
            f.stt_status = "running"
        if files:
            await self.session.flush()
        return files

    async def claim_ocr_pending_files(self, limit: int = 1) -> list[DriveFile]:
        """Claim files ready for OCR enrichment using SELECT FOR UPDATE SKIP LOCKED."""
        result = await self.session.execute(
            select(DriveFile)
            .where(
                DriveFile.enrichment_state.in_(["pending", "failed_partial"]),
                DriveFile.ocr_status == "pending",
                DriveFile.keyframe_s3_prefix.isnot(None),
                DriveFile.is_deleted.is_(False),
            )
            .order_by(DriveFile.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        files = list(result.scalars().all())
        for f in files:
            f.ocr_status = "running"
        if files:
            await self.session.flush()
        return files

    async def update_enrichment_status(
        self,
        file_id: UUID,
        ocr_status: str,
        enrichment_error: Optional[str] = None,
    ) -> None:
        """Update OCR status and recompute enrichment_state from stt+ocr."""
        result = await self.session.execute(
            select(DriveFile).where(DriveFile.id == file_id)
        )
        df = result.scalar_one()
        new_state = _compute_enrichment_state(df.stt_status, ocr_status, df.caption_status)

        values: dict[str, object] = {
            "ocr_status": ocr_status,
            "enrichment_state": new_state,
            "enrichment_updated_at": func.now(),
        }
        if enrichment_error is not None:
            values["enrichment_error"] = enrichment_error
        await self.session.execute(
            update(DriveFile).where(DriveFile.id == file_id).values(**values)
        )
        await self.session.flush()

    async def claim_caption_pending_files(self, limit: int = 1) -> list[DriveFile]:
        """Claim files ready for caption enrichment using SELECT FOR UPDATE SKIP LOCKED.

        Priority: only caption files where OCR+STT are already done/failed/null.
        Requires keyframe_s3_prefix to be set (needs keyframes for captioning).
        """
        result = await self.session.execute(
            select(DriveFile)
            .where(
                DriveFile.caption_status == "pending",
                DriveFile.keyframe_s3_prefix.isnot(None),
                DriveFile.is_deleted.is_(False),
            )
            .order_by(DriveFile.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        files = list(result.scalars().all())
        for f in files:
            f.caption_status = "running"
        if files:
            await self.session.flush()
        return files

    async def update_caption_enrichment_status(
        self,
        file_id: UUID,
        caption_status: str,
        caption_error: Optional[str] = None,
    ) -> None:
        """Update caption status and recompute enrichment_state from stt+ocr+caption."""
        result = await self.session.execute(
            select(DriveFile).where(DriveFile.id == file_id)
        )
        df = result.scalar_one()
        new_state = _compute_enrichment_state(df.stt_status, df.ocr_status, caption_status)

        values: dict[str, object] = {
            "caption_status": caption_status,
            "enrichment_state": new_state,
            "enrichment_updated_at": func.now(),
        }
        if caption_error is not None:
            values["caption_error"] = caption_error
        await self.session.execute(
            update(DriveFile).where(DriveFile.id == file_id).values(**values)
        )
        await self.session.flush()

    async def update_stt_enrichment_status(
        self,
        file_id: UUID,
        stt_status: str,
        enrichment_error: Optional[str] = None,
    ) -> None:
        result = await self.session.execute(
            select(DriveFile).where(DriveFile.id == file_id)
        )
        df = result.scalar_one()
        new_state = _compute_enrichment_state(stt_status, df.ocr_status, df.caption_status)

        values: dict[str, object] = {
            "stt_status": stt_status,
            "enrichment_state": new_state,
            "enrichment_updated_at": func.now(),
        }
        if enrichment_error is not None:
            values["enrichment_error"] = enrichment_error
        await self.session.execute(
            update(DriveFile).where(DriveFile.id == file_id).values(**values)
        )
        await self.session.flush()


def _compute_enrichment_state(
    stt_status: Optional[str], ocr_status: Optional[str], caption_status: Optional[str] = None,
) -> str:
    """Derive enrichment_state from stt_status + ocr_status.

    State priority: done > failed/failed_partial > running > pending.
    """
    active = [s for s in (stt_status, ocr_status, caption_status) if s is not None]
    if not active:
        return "pending"
    if all(s == "done" for s in active):
        return "done"
    if all(s in ("done", "failed") for s in active):
        return "failed" if all(s == "failed" for s in active) else "failed_partial"
    if any(s == "running" for s in active):
        return "running"
    return "pending"


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
