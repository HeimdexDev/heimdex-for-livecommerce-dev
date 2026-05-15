"""Async CRUD repository for ExportRecord.

All queries are org-scoped to enforce multi-tenant isolation.
"""
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ExportRecord


class ExportRecordRepository:
    def __init__(self, session: AsyncSession):
        self.session: AsyncSession = session

    async def create(
        self,
        *,
        org_id: UUID,
        user_id: UUID,
        export_hash: str,
        clip_count: int,
        proxy_count: int,
        sequence_name: str,
        request_body: dict[str, Any],
        expires_at: datetime,
    ) -> ExportRecord:
        """Create a new pending export record."""
        record = ExportRecord(
            org_id=org_id,
            user_id=user_id,
            export_hash=export_hash,
            clip_count=clip_count,
            proxy_count=proxy_count,
            sequence_name=sequence_name,
            request_body=request_body,
            expires_at=expires_at,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def get(self, export_id: UUID, org_id: UUID) -> Optional[ExportRecord]:
        """Get an export record by ID, scoped to org."""
        result = await self.session.execute(
            select(ExportRecord).where(
                ExportRecord.id == export_id,
                ExportRecord.org_id == org_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, export_id: UUID) -> Optional[ExportRecord]:
        """Get an export record by ID (no org scope — for worker use)."""
        result = await self.session.execute(
            select(ExportRecord).where(ExportRecord.id == export_id)
        )
        return result.scalar_one_or_none()

    async def find_cached(
        self,
        *,
        org_id: UUID,
        export_hash: str,
    ) -> Optional[ExportRecord]:
        """Find a ready, non-expired export with matching hash (cache hit)."""
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            select(ExportRecord).where(
                ExportRecord.org_id == org_id,
                ExportRecord.export_hash == export_hash,
                ExportRecord.status == "ready",
                ExportRecord.expires_at > now,
            ).order_by(ExportRecord.created_at.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    async def update_status(
        self,
        export_id: UUID,
        status: str,
        *,
        s3_key: Optional[str] = None,
        size_bytes: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update export record status and optional result fields."""
        values: dict[str, Any] = {
            "status": status,
            "updated_at": datetime.now(timezone.utc),
        }
        if s3_key is not None:
            values["s3_key"] = s3_key
        if size_bytes is not None:
            values["size_bytes"] = size_bytes
        if error_message is not None:
            values["error_message"] = error_message

        await self.session.execute(
            update(ExportRecord)
            .where(ExportRecord.id == export_id)
            .values(**values)
        )
        await self.session.flush()

    async def expire_stale(self) -> int:
        """Mark ready exports past their expiry as 'expired'. Returns count."""
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            update(ExportRecord)
            .where(
                ExportRecord.status == "ready",
                ExportRecord.expires_at <= now,
            )
            .values(status="expired", updated_at=now)
        )
        await self.session.flush()
        return result.rowcount  # type: ignore[return-value]
