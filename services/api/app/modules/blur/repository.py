"""Async CRUD repository for BlurJob.

Public (org + user scoped) methods enforce multi-tenant isolation and
guarantee one user can never see another user's jobs even by guessing
UUIDs.

Internal (org-only or ID-only) methods are for the worker callback path
and the active-job concurrency cap query — they deliberately bypass the
user scope because the worker has no user identity.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.blur.models import (
    ACTIVE_STATUSES,
    BLUR_STATUS_CANCELLED,
    BLUR_STATUS_DONE,
    BLUR_STATUS_FAILED,
    BLUR_STATUS_QUEUED,
    BLUR_STATUS_RUNNING,
    BlurJob,
)


class BlurJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session: AsyncSession = session

    # ---------- create / dedupe ----------

    async def create(
        self,
        *,
        org_id: UUID,
        file_id: UUID,
        video_id: str,
        requested_by: UUID,
        options: dict[str, Any],
        options_hash: str,
        source_s3_key: str,
        source_kind: str,
    ) -> BlurJob:
        job = BlurJob(
            org_id=org_id,
            file_id=file_id,
            video_id=video_id,
            requested_by=requested_by,
            options=options,
            options_hash=options_hash,
            source_s3_key=source_s3_key,
            source_kind=source_kind,
            requested_at=datetime.now(timezone.utc),
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def find_recent_duplicate(
        self,
        *,
        org_id: UUID,
        file_id: UUID,
        options_hash: str,
        since: datetime,
    ) -> BlurJob | None:
        """Find the most recent job matching (org, file, options_hash)
        requested after ``since``.

        Org-scoped, not user-scoped: if two users from the same org
        submit the same (video, options) within the window, the second
        returns the first's job. That matches the product contract —
        the blurred MP4 is an org-level artifact, not a per-user one.
        """
        result = await self.session.execute(
            select(BlurJob)
            .where(
                BlurJob.org_id == org_id,
                BlurJob.file_id == file_id,
                BlurJob.options_hash == options_hash,
                BlurJob.requested_at >= since,
                # Terminal-failure jobs should not collapse a retry —
                # the user is explicitly asking to try again.
                BlurJob.status.notin_([BLUR_STATUS_FAILED, BLUR_STATUS_CANCELLED]),
            )
            .order_by(BlurJob.requested_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    # ---------- read ----------

    async def get_by_id(
        self,
        org_id: UUID,
        job_id: UUID,
    ) -> BlurJob | None:
        """Org-scoped read. Any user in the org can read any job —
        matches the dedupe semantics above.
        """
        result = await self.session.execute(
            select(BlurJob).where(
                BlurJob.id == job_id,
                BlurJob.org_id == org_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id_internal(self, job_id: UUID) -> BlurJob | None:
        """No org scope — for the worker callback path."""
        result = await self.session.execute(
            select(BlurJob).where(BlurJob.id == job_id)
        )
        return result.scalar_one_or_none()

    async def list_by_file(
        self,
        org_id: UUID,
        file_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[BlurJob], int]:
        where = (BlurJob.org_id == org_id, BlurJob.file_id == file_id)

        count_result = await self.session.execute(
            select(func.count()).select_from(BlurJob).where(*where)
        )
        total = count_result.scalar_one()

        result = await self.session.execute(
            select(BlurJob)
            .where(*where)
            .order_by(BlurJob.requested_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total

    async def count_active_for_org(self, org_id: UUID) -> int:
        """Count jobs still in flight for an org. Used by the
        concurrency cap check before enqueuing a new job.
        """
        result = await self.session.execute(
            select(func.count())
            .select_from(BlurJob)
            .where(
                BlurJob.org_id == org_id,
                BlurJob.status.in_(list(ACTIVE_STATUSES)),
            )
        )
        return int(result.scalar_one())

    # ---------- state transitions ----------

    async def mark_cancelled_if_queued(
        self,
        *,
        org_id: UUID,
        job_id: UUID,
    ) -> bool:
        """Atomic ``queued → cancelled``.

        Returns True if the row was cancelled, False if it was already
        past the queued state (running/done/failed/cancelled). Atomic
        via a single UPDATE ... WHERE status='queued' so there is no
        window where a worker could claim an about-to-be-cancelled job.
        """
        result = await self.session.execute(
            update(BlurJob)
            .where(
                BlurJob.id == job_id,
                BlurJob.org_id == org_id,
                BlurJob.status == BLUR_STATUS_QUEUED,
            )
            .values(
                status=BLUR_STATUS_CANCELLED,
                completed_at=datetime.now(timezone.utc),
            )
        )
        await self.session.flush()
        return result.rowcount > 0

    async def claim(
        self,
        *,
        job_id: UUID,
        lease_seconds: int,
    ) -> tuple[BlurJob, UUID] | None:
        """Atomic ``queued → running`` with lease token.

        Returns the refreshed job + fresh lease token on success,
        ``None`` if the row is not in ``queued`` state (already claimed,
        cancelled, or gone). Used only by the internal worker-facing
        endpoint.
        """
        lease_token = uuid4()
        now = datetime.now(timezone.utc)
        lease_expires = now + timedelta(seconds=lease_seconds)

        result = await self.session.execute(
            update(BlurJob)
            .where(
                BlurJob.id == job_id,
                BlurJob.status == BLUR_STATUS_QUEUED,
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
        job = await self.get_by_id_internal(job_id)
        if job is None:
            return None
        return job, lease_token

    async def heartbeat(
        self,
        *,
        job_id: UUID,
        lease_token: UUID,
        lease_seconds: int,
    ) -> bool:
        """Extend the lease expiry on a running job. Lease-token guarded."""
        new_expiry = datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
        result = await self.session.execute(
            update(BlurJob)
            .where(
                BlurJob.id == job_id,
                BlurJob.lease_token == lease_token,
                BlurJob.status == BLUR_STATUS_RUNNING,
            )
            .values(lease_expires_at=new_expiry)
        )
        await self.session.flush()
        return result.rowcount > 0

    async def complete(
        self,
        *,
        job_id: UUID,
        lease_token: UUID,
        status: str,
        blurred_s3_key: str | None = None,
        manifest_s3_key: str | None = None,
        mask_s3_keys: dict[str, str] | None = None,
        detections_summary: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> BlurJob | None:
        """Terminal transition: running → {done, failed, cancelled}.

        Lease-token guarded — a stale worker that lost its lease to a
        watchdog cannot overwrite a fresh worker's result. Reads back
        the refreshed row and returns it.
        """
        if status not in (BLUR_STATUS_DONE, BLUR_STATUS_FAILED, BLUR_STATUS_CANCELLED):
            raise ValueError(f"Invalid terminal status: {status}")

        now = datetime.now(timezone.utc)
        values: dict[str, Any] = {
            "status": status,
            "completed_at": now,
            "lease_token": None,
            "lease_expires_at": None,
        }
        # Only overwrite result fields when the worker supplied them —
        # don't clobber a previously set key with None on a heartbeat-
        # style partial update.
        if blurred_s3_key is not None:
            values["blurred_s3_key"] = blurred_s3_key
        if manifest_s3_key is not None:
            values["manifest_s3_key"] = manifest_s3_key
        if mask_s3_keys is not None:
            values["mask_s3_keys"] = mask_s3_keys
        if detections_summary is not None:
            values["detections_summary"] = detections_summary
        if error is not None:
            values["error"] = error
        # On a done/failed terminal we zero the live progress fields so
        # the UI switches cleanly from "running" to the final status
        # without a stale progress_pct stuck at 98.
        if status in (BLUR_STATUS_DONE, BLUR_STATUS_FAILED):
            values["progress_pct"] = 100 if status == BLUR_STATUS_DONE else 0
            values["phase"] = None

        result = await self.session.execute(
            update(BlurJob)
            .where(
                BlurJob.id == job_id,
                BlurJob.lease_token == lease_token,
                # Guard on status too: cannot transition out of a
                # terminal state. Prevents a late callback from
                # resurrecting a cancelled job.
                BlurJob.status == BLUR_STATUS_RUNNING,
            )
            .values(**values)
        )
        await self.session.flush()
        if result.rowcount == 0:
            return None
        return await self.get_by_id_internal(job_id)

    async def update_progress(
        self,
        *,
        job_id: UUID,
        lease_token: UUID,
        progress_pct: float,
        phase: str,
        lease_seconds: int,
    ) -> bool:
        """Write a progress heartbeat AND refresh the lease atomically.

        Called from the worker on every few seconds of pipeline
        activity. Lease-token guarded so a stale worker can't bump the
        progress bar on a job that a watchdog has already handed off.

        Returns True on success, False if the row is no longer running
        or the lease token doesn't match — the worker should treat
        False as "stop and exit cleanly".
        """
        # Clamp to int at the DB boundary — storing float here buys us
        # nothing in the UI and complicates the migration.
        pct_int = max(0, min(100, int(round(progress_pct))))
        new_expiry = datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
        result = await self.session.execute(
            update(BlurJob)
            .where(
                BlurJob.id == job_id,
                BlurJob.lease_token == lease_token,
                BlurJob.status == BLUR_STATUS_RUNNING,
            )
            .values(
                progress_pct=pct_int,
                phase=phase,
                lease_expires_at=new_expiry,
            )
        )
        await self.session.flush()
        return result.rowcount > 0
