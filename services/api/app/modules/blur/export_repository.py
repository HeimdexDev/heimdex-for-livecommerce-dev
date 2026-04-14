"""Async CRUD repository for :class:`BlurExport`.

Mirrors the shape of :mod:`app.modules.blur.repository` so both halves
of the blur subsystem share the same transitional vocabulary (create /
dedupe / claim / complete / cancel). The export worker never imports
this module — it talks to the internal router over HTTP.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.blur.models import (
    ACTIVE_STATUSES,
    BLUR_STATUS_CANCELLED,
    BLUR_STATUS_DONE,
    BLUR_STATUS_FAILED,
    BLUR_STATUS_QUEUED,
    BLUR_STATUS_RUNNING,
    BlurExport,
)


class BlurExportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session: AsyncSession = session

    # ---------- create / dedupe ----------

    async def create(
        self,
        *,
        org_id: UUID,
        blur_job_id: UUID,
        file_id: UUID,
        video_id: str,
        requested_by: UUID,
        categories: list[str],
        categories_hash: str,
        format_: str,
    ) -> BlurExport:
        row = BlurExport(
            org_id=org_id,
            blur_job_id=blur_job_id,
            file_id=file_id,
            video_id=video_id,
            requested_by=requested_by,
            categories=categories,
            categories_hash=categories_hash,
            format=format_,
            requested_at=datetime.now(timezone.utc),
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def find_recent_duplicate(
        self,
        *,
        blur_job_id: UUID,
        categories_hash: str,
        format_: str,
        since: datetime,
    ) -> BlurExport | None:
        """Short-window idempotency for export requests.

        Keyed on (blur_job_id, categories_hash, format) since an
        export's category subset is the only thing that changes
        between requests against the same parent job.
        """
        result = await self.session.execute(
            select(BlurExport)
            .where(
                BlurExport.blur_job_id == blur_job_id,
                BlurExport.categories_hash == categories_hash,
                BlurExport.format == format_,
                BlurExport.requested_at >= since,
                BlurExport.status.notin_([BLUR_STATUS_FAILED, BLUR_STATUS_CANCELLED]),
            )
            .order_by(BlurExport.requested_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    # ---------- read ----------

    async def get_by_id(
        self,
        org_id: UUID,
        export_id: UUID,
    ) -> BlurExport | None:
        """Org-scoped read used by public routes."""
        result = await self.session.execute(
            select(BlurExport).where(
                BlurExport.id == export_id,
                BlurExport.org_id == org_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id_internal(self, export_id: UUID) -> BlurExport | None:
        """No org scope — for the worker callback path."""
        result = await self.session.execute(
            select(BlurExport).where(BlurExport.id == export_id)
        )
        return result.scalar_one_or_none()

    async def count_active_for_org(self, org_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(BlurExport)
            .where(
                BlurExport.org_id == org_id,
                BlurExport.status.in_(list(ACTIVE_STATUSES)),
            )
        )
        return int(result.scalar_one())

    # ---------- state transitions ----------

    async def claim(
        self,
        *,
        export_id: UUID,
        lease_seconds: int,
    ) -> tuple[BlurExport, UUID] | None:
        lease_token = uuid4()
        now = datetime.now(timezone.utc)
        lease_expires = now + timedelta(seconds=lease_seconds)

        result = await self.session.execute(
            update(BlurExport)
            .where(
                BlurExport.id == export_id,
                BlurExport.status == BLUR_STATUS_QUEUED,
            )
            .values(
                status=BLUR_STATUS_RUNNING,
                started_at=now,
                lease_token=lease_token,
                lease_expires_at=lease_expires,
            )
        )
        await self.session.flush()
        if result.rowcount == 0:
            return None
        row = await self.get_by_id_internal(export_id)
        if row is None:
            return None
        return row, lease_token

    async def complete(
        self,
        *,
        export_id: UUID,
        lease_token: UUID,
        status: str,
        layer_s3_key: str | None = None,
        error: str | None = None,
    ) -> BlurExport | None:
        if status not in (BLUR_STATUS_DONE, BLUR_STATUS_FAILED, BLUR_STATUS_CANCELLED):
            raise ValueError(f"Invalid terminal status: {status}")

        now = datetime.now(timezone.utc)
        values: dict[str, Any] = {
            "status": status,
            "completed_at": now,
            "lease_token": None,
            "lease_expires_at": None,
        }
        if layer_s3_key is not None:
            values["layer_s3_key"] = layer_s3_key
        if error is not None:
            values["error"] = error

        result = await self.session.execute(
            update(BlurExport)
            .where(
                BlurExport.id == export_id,
                BlurExport.lease_token == lease_token,
                BlurExport.status == BLUR_STATUS_RUNNING,
            )
            .values(**values)
        )
        await self.session.flush()
        if result.rowcount == 0:
            return None
        return await self.get_by_id_internal(export_id)
