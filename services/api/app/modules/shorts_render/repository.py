"""Async CRUD repository for ShortsRenderJob.

Org-scoped queries enforce multi-tenant isolation where applicable.
Internal methods (update_status, list_expired) omit org scope for worker use.
"""
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ShortsRenderJob


class ShortsRenderJobRepository:
    def __init__(self, session: AsyncSession):
        self.session: AsyncSession = session

    async def create(
        self,
        *,
        org_id: UUID,
        user_id: UUID,
        video_id: str,
        title: str | None,
        input_spec: dict[str, Any],
        expires_at: datetime | None,
        composition_hash: str | None = None,
    ) -> ShortsRenderJob:
        """Create a new render job (status set by server_default)."""
        job = ShortsRenderJob(
            org_id=org_id,
            user_id=user_id,
            video_id=video_id,
            title=title,
            input_spec=input_spec,
            expires_at=expires_at,
            composition_hash=composition_hash,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get_by_id(
        self,
        org_id: UUID,
        user_id: UUID,
        job_id: UUID,
    ) -> ShortsRenderJob | None:
        """Get a render job by ID, scoped to org AND user.

        Previously org-scoped only; now also filters on ``user_id`` so a
        user cannot view another user's render job in the same org even
        if they guess the UUID. Internal callers (worker status
        callbacks) use ``_get_by_id_internal`` and bypass this check.
        """
        result = await self.session.execute(
            select(ShortsRenderJob).where(
                ShortsRenderJob.id == job_id,
                ShortsRenderJob.org_id == org_id,
                ShortsRenderJob.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def find_recent_duplicate(
        self,
        *,
        org_id: UUID,
        user_id: UUID,
        composition_hash: str,
        since: datetime,
    ) -> ShortsRenderJob | None:
        """Find the most recent job whose (org, user, hash) matches and
        was created after ``since``. Used by the idempotency check to
        collapse accidental double-submissions.

        Returns None if no recent match — the caller should proceed with
        a fresh create. Jobs in any status (queued / rendering /
        completed / failed) count as duplicates so a retry during an
        in-flight render returns the existing in-flight job, not a new
        one.
        """
        result = await self.session.execute(
            select(ShortsRenderJob)
            .where(
                ShortsRenderJob.org_id == org_id,
                ShortsRenderJob.user_id == user_id,
                ShortsRenderJob.composition_hash == composition_hash,
                ShortsRenderJob.created_at >= since,
            )
            .order_by(ShortsRenderJob.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _get_by_id_internal(self, job_id: UUID) -> ShortsRenderJob | None:
        """Get a render job by ID (no org scope — for internal/worker use)."""
        result = await self.session.execute(
            select(ShortsRenderJob).where(ShortsRenderJob.id == job_id)
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        org_id: UUID,
        user_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[ShortsRenderJob], int]:
        """List render jobs for a user with pagination. Returns (jobs, total_count)."""
        where = (
            ShortsRenderJob.org_id == org_id,
            ShortsRenderJob.user_id == user_id,
        )

        count_result = await self.session.execute(
            select(func.count()).select_from(ShortsRenderJob).where(*where)
        )
        total = count_result.scalar_one()

        result = await self.session.execute(
            select(ShortsRenderJob)
            .where(*where)
            .order_by(ShortsRenderJob.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        jobs = list(result.scalars().all())
        return jobs, total

    async def update_status(
        self,
        job_id: UUID,
        status: str,
        **kwargs: Any,
    ) -> ShortsRenderJob | None:
        """Update job status and optional result fields. Returns refreshed job or None."""
        values: dict[str, Any] = {
            "status": status,
            "updated_at": datetime.now(timezone.utc),
        }
        if status in ("completed", "failed"):
            values["completed_at"] = datetime.now(timezone.utc)

        for key in ("output_s3_key", "output_duration_ms", "output_size_bytes", "render_time_ms", "error"):
            if key in kwargs:
                values[key] = kwargs[key]

        result = await self.session.execute(
            update(ShortsRenderJob)
            .where(ShortsRenderJob.id == job_id)
            .values(**values)
        )
        await self.session.flush()

        if result.rowcount == 0:
            return None

        return await self._get_by_id_internal(job_id)

    async def update_title(
        self,
        org_id: UUID,
        user_id: UUID,
        job_id: UUID,
        title: str | None,
    ) -> ShortsRenderJob | None:
        """Update the user-visible title on a render job.

        Scoped to org + user so a guess at someone else's job UUID
        can't rename their work. ``None`` clears the title back to
        the default fallback the FE will compute. Returns the
        refreshed job, or ``None`` when the job doesn't exist or
        isn't owned by ``(org_id, user_id)``.
        """
        job = await self.get_by_id(org_id, user_id, job_id)
        if job is None:
            return None
        await self.session.execute(
            update(ShortsRenderJob)
            .where(ShortsRenderJob.id == job_id)
            .values(title=title, updated_at=datetime.now(timezone.utc))
        )
        await self.session.flush()
        return await self._get_by_id_internal(job_id)

    async def delete(self, org_id: UUID, user_id: UUID, job_id: UUID) -> bool:
        """Delete a render job by ID, scoped to org + user.

        Internal system-level cleanup goes through
        ``delete_one_by_id_internal`` instead.
        """
        job = await self.get_by_id(org_id, user_id, job_id)
        if job is None:
            return False
        await self.session.delete(job)
        await self.session.flush()
        return True

    async def list_expired(self, now: datetime) -> list[ShortsRenderJob]:
        """List expired jobs that have output files (for cleanup).

        Excludes jobs still in flight (status rendering/queued) so a slow
        worker's long-running job is never torn out from under it.
        """
        result = await self.session.execute(
            select(ShortsRenderJob).where(
                ShortsRenderJob.expires_at < now,
                ShortsRenderJob.output_s3_key.is_not(None),
                ShortsRenderJob.status.in_(("completed", "failed")),
            )
        )
        return list(result.scalars().all())

    async def list_expired_without_output(self, now: datetime) -> list[ShortsRenderJob]:
        """List expired jobs that have no output (failed / orphaned queued).

        Used by the cleanup sweep to drop DB rows that would otherwise
        accumulate forever — list_expired() only returns rows with an
        output_s3_key, so failed jobs never get cleaned up by that path.
        """
        result = await self.session.execute(
            select(ShortsRenderJob).where(
                ShortsRenderJob.expires_at < now,
                ShortsRenderJob.output_s3_key.is_(None),
                ShortsRenderJob.status.in_(("failed", "queued")),
            )
        )
        return list(result.scalars().all())

    async def delete_one_by_id_internal(self, job_id: UUID) -> bool:
        """Delete a job by ID without org scoping.

        Distinct from ``delete(org_id, job_id)`` — the cleanup sweep runs
        as a system process with no org context. Never expose this method
        through a user-facing endpoint.
        """
        job = await self._get_by_id_internal(job_id)
        if job is None:
            return False
        await self.session.delete(job)
        await self.session.flush()
        return True
