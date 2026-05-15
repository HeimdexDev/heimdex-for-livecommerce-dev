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
        idempotency_key: str | None = None,
    ) -> ShortsRenderJob:
        """Create a new render job (status set by server_default).

        ``idempotency_key`` (migration 057) scopes the dedupe lookup
        in :meth:`find_recent_duplicate`. Wizard child runs pass
        ``str(scan_job_id)`` so a crash-retry collapses but two
        different scan_jobs with identical compositions stay
        distinct. Leave NULL for direct user-click renders.
        """
        job = ShortsRenderJob(
            org_id=org_id,
            user_id=user_id,
            video_id=video_id,
            title=title,
            input_spec=input_spec,
            expires_at=expires_at,
            composition_hash=composition_hash,
            idempotency_key=idempotency_key,
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
        idempotency_key: str | None = None,
    ) -> ShortsRenderJob | None:
        """Find the most recent job whose (org, user, hash, key) matches
        and was created after ``since``.

        ``idempotency_key`` (migration 057) scopes the match:

        - ``None`` → only matches rows with ``idempotency_key IS NULL``
          (legacy semantics; preserves direct-user-click dedupe).
        - non-None → matches rows with the SAME key only. Different
          scan_jobs with identical compositions but different
          ``scan_job_id``-derived keys will NOT collide.

        Returns ``None`` if no recent match — the caller should proceed
        with a fresh create. Jobs in any status (queued / rendering /
        completed / failed) count as duplicates so a retry during an
        in-flight render returns the existing in-flight job, not a new
        one.

        The dedupe index ``ix_shorts_render_jobs_dedupe`` covers
        ``(org_id, user_id, composition_hash, idempotency_key,
        created_at)`` so both the IS NULL and = comparisons hit the
        same B-tree.
        """
        if idempotency_key is None:
            key_clause = ShortsRenderJob.idempotency_key.is_(None)
        else:
            key_clause = ShortsRenderJob.idempotency_key == idempotency_key
        result = await self.session.execute(
            select(ShortsRenderJob)
            .where(
                ShortsRenderJob.org_id == org_id,
                ShortsRenderJob.user_id == user_id,
                ShortsRenderJob.composition_hash == composition_hash,
                key_clause,
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
        """List render jobs for a user with pagination. Returns (jobs, total_count).

        Filters out intermediate (superseded) renders — rows whose
        ``replaced_by_render_job_id`` points at a refined child. The
        saved-shorts UI shows one logical short per chain; surfacing
        intermediates duplicates the same content with stale subtitles
        and confuses operators after a Whisper / manual_edit rerender.

        To inspect a chain's history (audit / debugging), use
        ``get_by_id`` directly with the intermediate's id — the row
        still exists in the table, it's just hidden from the user-
        facing listing.
        """
        where = (
            ShortsRenderJob.org_id == org_id,
            ShortsRenderJob.user_id == user_id,
            ShortsRenderJob.replaced_by_render_job_id.is_(None),
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

    async def walk_to_leaf(
        self,
        org_id: UUID,
        user_id: UUID,
        job_id: UUID,
        *,
        max_depth: int = 8,
    ) -> ShortsRenderJob | None:
        """Walk ``replaced_by_render_job_id`` forward to the chain's leaf.

        Returns the row at the end of the chain (where
        ``replaced_by_render_job_id IS NULL``). Returns the starting
        row if it's already the leaf, or ``None`` if the starting row
        doesn't exist / isn't owned by this (org, user).

        Bounded by ``max_depth`` (default 8) as a defense against
        pathological state — the chain depth in practice is ≤ 3
        (Whisper refine + 1-2 manual_edit re-saves). FK constraints
        prevent literal cycles, but a deleted leaf can produce a
        broken chain: in that case we return the last row before the
        dangling pointer rather than failing — the caller (e.g.
        ``_to_response``) treats it as "leaf reached" and uses that
        row's MP4 as the download target.
        """
        current = await self.get_by_id(org_id, user_id, job_id)
        if current is None:
            return None

        for _ in range(max_depth):
            if current.replaced_by_render_job_id is None:
                return current
            next_job = await self.get_by_id(
                org_id, user_id, current.replaced_by_render_job_id,
            )
            if next_job is None:
                # Broken chain (deleted refined child). The last
                # reachable row is the effective leaf for download
                # purposes.
                return current
            current = next_job

        # max_depth reached without finding a leaf — return whatever
        # we last saw rather than looping forever.
        return current

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

    async def complete_idempotent(
        self,
        job_id: UUID,
        *,
        output_s3_key: str | None,
        output_duration_ms: int | None,
        output_size_bytes: int | None,
        render_time_ms: int | None,
    ) -> bool:
        """Atomically flip a job to ``completed`` if it isn't already.

        Returns ``True`` iff this call was the one that flipped the
        row. ``False`` means either:
        - the row was already completed (SQS redelivery / retry); or
        - the row doesn't exist (caller should 404 separately if it
          cares — check via ``_get_by_id_internal`` BEFORE calling
          this method to distinguish).

        Used by the worker callback path so the post-render Whisper
        refinement hook fires exactly once per render, even when
        the worker's status callback is double-delivered.

        Distinct from ``update_status`` (which always overwrites,
        no idempotency guard) — kept separate to preserve the
        existing behaviour for non-completed transitions.
        """
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            update(ShortsRenderJob)
            .where(
                ShortsRenderJob.id == job_id,
                ShortsRenderJob.status != "completed",
            )
            .values(
                status="completed",
                completed_at=now,
                updated_at=now,
                output_s3_key=output_s3_key,
                output_duration_ms=output_duration_ms,
                output_size_bytes=output_size_bytes,
                render_time_ms=render_time_ms,
            )
        )
        await self.session.flush()
        return result.rowcount > 0

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

    async def persist_summary(
        self,
        org_id: UUID,
        user_id: UUID,
        job_id: UUID,
        *,
        summary: str,
        prompt_version: str,
        generated_at: datetime,
    ) -> ShortsRenderJob | None:
        """Persist a freshly generated per-short summary (migration 059).

        Scoped to org + user — same guard as ``update_title`` so a
        guessed job UUID can't write into another user's row. Returns
        the refreshed job, or ``None`` when the job doesn't exist or
        isn't owned by ``(org_id, user_id)``. Overwrites any existing
        summary: a regenerate (prompt-version bump or an explicit
        re-request) replaces the canonical column.
        """
        job = await self.get_by_id(org_id, user_id, job_id)
        if job is None:
            return None
        await self.session.execute(
            update(ShortsRenderJob)
            .where(ShortsRenderJob.id == job_id)
            .values(
                summary=summary,
                summary_prompt_version=prompt_version,
                summary_generated_at=generated_at,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self.session.flush()
        return await self._get_by_id_internal(job_id)

    async def create_rerender_child(
        self,
        *,
        org_id: UUID,
        user_id: UUID,
        parent_job_id: UUID,
        composition_hash: str,
    ) -> ShortsRenderJob | None:
        """Insert a child render row carrying the parent's current ``input_spec``.

        Used by the manual subtitle-edit "Render with my edits" flow
        (plan: ``.claude/plans/auto-shorts-subtitle-editor-2026-05-06.md``).
        The child inherits ``org_id``, ``user_id``, ``video_id``,
        ``title``, ``expires_at``, AND ``input_spec`` (which already
        carries the operator's edited subtitles via prior PATCH
        ``/subtitles`` calls). ``refined_from_render_job_id`` points
        back at the parent and ``refinement_source='manual_edit'`` is
        carried forward (or set fresh when the parent had ``None``).

        Owner-scoped via ``get_by_id`` — returns ``None`` when the
        parent is missing or owned by a different ``(org_id, user_id)``.
        Also returns ``None`` when the parent isn't in the
        ``completed`` state — re-rendering an in-flight or failed
        parent has unclear semantics; the service surfaces this as a
        409 to the operator.

        ``composition_hash`` is computed by the caller (the service
        already has the helper) and passed in so the repository
        stays free of hashing concerns.
        """
        parent = await self.get_by_id(org_id, user_id, parent_job_id)
        if parent is None:
            return None
        if parent.status != "completed":
            return None

        child = ShortsRenderJob(
            org_id=parent.org_id,
            user_id=parent.user_id,
            video_id=parent.video_id,
            title=parent.title,
            input_spec=parent.input_spec,
            expires_at=parent.expires_at,
            composition_hash=composition_hash,
            refined_from_render_job_id=parent.id,
            # Inherit the source — typically 'manual_edit' set by
            # PATCH /subtitles. If the parent was a Whisper-refined
            # row with refinement_source='whisper', and the operator
            # rerenders it without editing, that's a no-op of sorts;
            # the resulting child is still flagged 'whisper'. Edge
            # case — operators typically edit before rerendering.
            refinement_source=parent.refinement_source,
        )
        self.session.add(child)
        await self.session.flush()
        return child

    async def update_subtitles_with_manual_edit(
        self,
        org_id: UUID,
        user_id: UUID,
        job_id: UUID,
        subtitles: list[dict[str, Any]],
    ) -> ShortsRenderJob | None:
        """Replace ``input_spec.subtitles`` and mark as manually edited.

        Atomic in a single ``UPDATE``: both the JSONB rewrite and the
        ``refinement_source='manual_edit'`` flag flip happen together.
        That flag is what the post-render Whisper hook checks via
        ``_check_guards`` to refuse overwriting operator-edited
        subtitles.

        Org+user-scoped via ``get_by_id`` — a guess at someone else's
        job UUID returns ``None``. Returns the refreshed job, or
        ``None`` when the row doesn't exist or isn't owned by
        ``(org_id, user_id)``.

        ``subtitles`` is a list of plain dicts (already validated as
        :class:`SubtitleSpec` at the router layer; we accept dicts
        here so the repository stays free of contract-package
        imports).

        Note: assigning a NEW dict to the JSONB column triggers the
        update; in-place mutation of ``job.input_spec`` would not
        reach the DB because SQLAlchemy doesn't track JSONB internal
        changes by default.
        """
        job = await self.get_by_id(org_id, user_id, job_id)
        if job is None:
            return None
        new_spec = {**(job.input_spec or {}), "subtitles": subtitles}
        await self.session.execute(
            update(ShortsRenderJob)
            .where(ShortsRenderJob.id == job_id)
            .values(
                input_spec=new_spec,
                refinement_source="manual_edit",
                updated_at=datetime.now(timezone.utc),
            )
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
