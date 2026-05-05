"""ProductScanJobRepository — async job lifecycle for product mode v2.

State transitions:
* User triggers scan / pick → ``create_*`` row inserted as ``queued``.
* Worker dequeues → ``claim`` advances to ``enumerating`` / ``tracking``
  and sets ``claimed_by`` + lease.
* Worker progress → ``heartbeat`` extends lease, accumulates cost.
* Worker terminal → ``complete_*`` or ``fail``.
* User cancel → ``cancel`` (only effective at next heartbeat).

Lease ownership: every mutation through the worker callback path
asserts ``claimed_by == row.claimed_by`` so a re-claimed (lease-
expired) job cannot be double-finished by a stale worker.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.shorts_auto_product.models import (
    ACTIVE_SCAN_STAGES,
    SCAN_MODE_ENUMERATE,
    SCAN_MODE_RENDER_CHILD,
    SCAN_MODE_SCAN_ORDER,
    SCAN_STAGE_ASSEMBLING,
    SCAN_STAGE_CANCELLED,
    SCAN_STAGE_DONE,
    SCAN_STAGE_ENUMERATING,
    SCAN_STAGE_ENUMERATION_DONE,
    SCAN_STAGE_FAILED,
    SCAN_STAGE_QUEUED,
    SCAN_STAGE_RENDERING,
    SCAN_STAGE_TRACKING,
    TERMINAL_SCAN_STAGES,
    ProductScanJob,
)


class ProductScanJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session: AsyncSession = session

    # ---------- create ----------

    async def create_enumeration_job(
        self,
        *,
        org_id: UUID,
        video_id: UUID,
        user_id: UUID,
        duration_preset_sec: int,
    ) -> ProductScanJob:
        job = ProductScanJob(
            org_id=org_id,
            video_id=video_id,
            requested_by_user_id=user_id,
            catalog_entry_id=None,
            duration_preset_sec=duration_preset_sec,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def create_tracking_job(
        self,
        *,
        org_id: UUID,
        video_id: UUID,
        user_id: UUID,
        catalog_entry_id: UUID,
        duration_preset_sec: int,
    ) -> ProductScanJob:
        job = ProductScanJob(
            org_id=org_id,
            video_id=video_id,
            requested_by_user_id=user_id,
            catalog_entry_id=catalog_entry_id,
            duration_preset_sec=duration_preset_sec,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    # ---------- read ----------

    async def get(
        self,
        *,
        org_id: UUID,
        job_id: UUID,
    ) -> ProductScanJob | None:
        stmt = select(ProductScanJob).where(
            ProductScanJob.id == job_id,
            ProductScanJob.org_id == org_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_internal(self, *, job_id: UUID) -> ProductScanJob | None:
        """ID-only fetch for the worker callback path. Org guard is
        enforced by the caller via ``claimed_by`` check + Bearer auth."""
        stmt = select(ProductScanJob).where(ProductScanJob.id == job_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def find_recent_duplicate(
        self,
        *,
        org_id: UUID,
        video_id: UUID,
        user_id: UUID,
        catalog_entry_id: UUID | None,
        within_seconds: int,
    ) -> ProductScanJob | None:
        """Idempotency lookup for the legacy scan + clip endpoints.

        Two requests with the same (org_id, video_id, user_id,
        catalog_entry_id) within ``within_seconds`` return the existing
        job. Includes terminal states — re-clicking a finished scan
        opens the cached result rather than starting a new one.

        ``org_id`` filter is mandatory (codex defensive fix). Without
        it, two orgs that happen to reference the same ``video_id``
        could collide on dedupe. Postgres FK on ``video_id`` already
        scopes uniqueness per ``drive_files`` row, but this query is
        defense in depth — and matches every other tenant-scoped
        repository read in this module.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=within_seconds)
        conditions: list[Any] = [
            ProductScanJob.org_id == org_id,
            ProductScanJob.video_id == video_id,
            ProductScanJob.requested_by_user_id == user_id,
            ProductScanJob.created_at >= cutoff,
        ]
        if catalog_entry_id is None:
            conditions.append(ProductScanJob.catalog_entry_id.is_(None))
        else:
            conditions.append(ProductScanJob.catalog_entry_id == catalog_entry_id)
        stmt = (
            select(ProductScanJob)
            .where(and_(*conditions))
            .order_by(ProductScanJob.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def find_latest_enumeration_for_video(
        self,
        *,
        org_id: UUID,
        video_id: UUID,
    ) -> ProductScanJob | None:
        """Most recent enumeration job for ``(org, video)`` regardless
        of which user requested it. Drives the ``scan_status`` field on
        the catalog response so a second user opening the same video
        sees "scan in progress" instead of "never scanned"."""
        stmt = (
            select(ProductScanJob)
            .where(
                ProductScanJob.org_id == org_id,
                ProductScanJob.video_id == video_id,
                ProductScanJob.catalog_entry_id.is_(None),
            )
            .order_by(ProductScanJob.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def count_active_for_org(self, *, org_id: UUID) -> int:
        stmt = (
            select(func.count(ProductScanJob.id))
            .where(
                ProductScanJob.org_id == org_id,
                ProductScanJob.stage.in_(list(ACTIVE_SCAN_STAGES)),
            )
        )
        return int((await self.session.execute(stmt)).scalar_one() or 0)

    # ---------- worker lease ----------

    async def claim(
        self,
        *,
        job_id: UUID,
        claimed_by: str,
        lease_seconds: int,
        next_stage: str,
    ) -> ProductScanJob | None:
        """Atomically transition ``queued → next_stage`` and set
        the lease.

        Returns the claimed row, or ``None`` if the job was already
        claimed / completed (idempotent — the worker can safely retry
        and another worker will not steal the lease).
        """
        if next_stage not in {
            SCAN_STAGE_ENUMERATING,
            SCAN_STAGE_TRACKING,
            SCAN_STAGE_ASSEMBLING,  # Phase 4: child runner claims queued → assembling
        }:
            raise ValueError(f"invalid claim next_stage: {next_stage!r}")
        now = datetime.now(timezone.utc)
        lease_expires = now + timedelta(seconds=lease_seconds)
        stmt = (
            update(ProductScanJob)
            .where(
                ProductScanJob.id == job_id,
                ProductScanJob.stage == SCAN_STAGE_QUEUED,
            )
            .values(
                stage=next_stage,
                claimed_by=claimed_by,
                claimed_at=now,
                lease_expires_at=lease_expires,
                last_heartbeat_at=now,
                started_at=now,
            )
            .returning(ProductScanJob)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def heartbeat(
        self,
        *,
        job_id: UUID,
        claimed_by: str,
        stage: str,
        progress_pct: int,
        progress_label: str | None,
        cost_delta_usd: Decimal,
        lease_seconds: int,
    ) -> ProductScanJob | None:
        """Extend lease + advance progress + accumulate cost.

        Guarded on ``claimed_by`` so a stale worker whose lease expired
        and was re-claimed cannot overwrite the new owner.
        """
        now = datetime.now(timezone.utc)
        lease_expires = now + timedelta(seconds=lease_seconds)
        stmt = (
            update(ProductScanJob)
            .where(
                ProductScanJob.id == job_id,
                ProductScanJob.claimed_by == claimed_by,
            )
            .values(
                stage=stage,
                progress_pct=progress_pct,
                progress_label=progress_label,
                last_heartbeat_at=now,
                lease_expires_at=lease_expires,
                cost_usd_estimate=ProductScanJob.cost_usd_estimate + cost_delta_usd,
            )
            .returning(ProductScanJob)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def complete_enumeration(
        self,
        *,
        job_id: UUID,
        claimed_by: str,
        cost_delta_usd: Decimal,
    ) -> ProductScanJob | None:
        return await self._complete(
            job_id=job_id,
            claimed_by=claimed_by,
            cost_delta_usd=cost_delta_usd,
            terminal_stage=SCAN_STAGE_ENUMERATION_DONE,
            render_job_id=None,
        )

    async def complete_tracking(
        self,
        *,
        job_id: UUID,
        claimed_by: str,
        cost_delta_usd: Decimal,
        render_job_id: UUID | None,
    ) -> ProductScanJob | None:
        return await self._complete(
            job_id=job_id,
            claimed_by=claimed_by,
            cost_delta_usd=cost_delta_usd,
            terminal_stage=SCAN_STAGE_DONE,
            render_job_id=render_job_id,
        )

    async def transition_parent_to_fanned_out(
        self,
        *,
        job_id: UUID,
        claimed_by: str,
        cost_delta_usd: Decimal,
    ) -> ProductScanJob | None:
        """Transition a wizard scan_order parent from tracking →
        fanned_out (Phase 4).

        Differs from ``complete_tracking`` in two key ways:
          * ``stage`` lands on ``SCAN_STAGE_FANNED_OUT`` (NOT DONE).
            The parent isn't terminal yet — it stays at fanned_out
            until all N children terminate.
          * ``completed_at`` stays NULL — the parent's "complete" is
            the workflow's pivot point to children, not the workflow's
            end.

        Releases the worker lease (claimed_by=None) since no further
        worker callbacks are expected on the parent. The cost delta
        from this final heartbeat rolls in atomically.

        Guarded on ``mode = SCAN_MODE_SCAN_ORDER`` AND ``claimed_by``
        match — defense in depth so a buggy worker can't transition
        the wrong job kind via this method.
        """
        from app.modules.shorts_auto_product.models import (
            SCAN_MODE_SCAN_ORDER,
            SCAN_STAGE_FANNED_OUT,
        )

        now = datetime.now(timezone.utc)
        stmt = (
            update(ProductScanJob)
            .where(
                ProductScanJob.id == job_id,
                ProductScanJob.claimed_by == claimed_by,
                ProductScanJob.mode == SCAN_MODE_SCAN_ORDER,
            )
            .values(
                stage=SCAN_STAGE_FANNED_OUT,
                progress_pct=100,
                last_heartbeat_at=now,
                claimed_by=None,
                lease_expires_at=None,
                cost_usd_estimate=(
                    ProductScanJob.cost_usd_estimate + cost_delta_usd
                ),
            )
            .returning(ProductScanJob)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def transition_parent_to_fanned_out_unclaimed(
        self,
        *,
        job_id: UUID,
    ) -> ProductScanJob | None:
        """Variant of :meth:`transition_parent_to_fanned_out` for the
        STT-mode inline fan-out path (PR 2.6).

        The SAM2-driven flow has the worker holding the parent's lease
        when it transitions to ``fanned_out``; the existing method's
        ``claimed_by`` guard is the right defense for that path. The
        STT-mode path runs INSIDE the api at scan_order creation time,
        before any worker has touched the row, so there is no lease to
        match. This method skips the claimed_by check.

        Same end-state as the worker path: ``stage=fanned_out``,
        ``claimed_by=None``, ``lease_expires_at=None``,
        ``progress_pct=100``, ``last_heartbeat_at=NOW``. No cost delta
        — STT-mode doesn't incur tracking cost at fan-out time
        (per-child STT pipeline cost is recorded by the runner).

        Guarded on ``mode = SCAN_MODE_SCAN_ORDER`` so a buggy caller
        can't accidentally use this on an enumerate or render_child
        row. Returns ``None`` if no row matched (parent missing or
        wrong mode).
        """
        from app.modules.shorts_auto_product.models import (
            SCAN_MODE_SCAN_ORDER,
            SCAN_STAGE_FANNED_OUT,
        )

        now = datetime.now(timezone.utc)
        stmt = (
            update(ProductScanJob)
            .where(
                ProductScanJob.id == job_id,
                ProductScanJob.mode == SCAN_MODE_SCAN_ORDER,
            )
            .values(
                stage=SCAN_STAGE_FANNED_OUT,
                progress_pct=100,
                last_heartbeat_at=now,
                claimed_by=None,
                lease_expires_at=None,
            )
            .returning(ProductScanJob)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _complete(
        self,
        *,
        job_id: UUID,
        claimed_by: str,
        cost_delta_usd: Decimal,
        terminal_stage: str,
        render_job_id: UUID | None,
    ) -> ProductScanJob | None:
        now = datetime.now(timezone.utc)
        values: dict[str, Any] = {
            "stage": terminal_stage,
            "progress_pct": 100,
            "completed_at": now,
            "last_heartbeat_at": now,
            "claimed_by": None,
            "lease_expires_at": None,
            "cost_usd_estimate": (
                ProductScanJob.cost_usd_estimate + cost_delta_usd
            ),
        }
        if render_job_id is not None:
            values["render_job_id"] = render_job_id
        stmt = (
            update(ProductScanJob)
            .where(
                ProductScanJob.id == job_id,
                ProductScanJob.claimed_by == claimed_by,
            )
            .values(**values)
            .returning(ProductScanJob)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def fail(
        self,
        *,
        job_id: UUID,
        claimed_by: str,
        error_code: str,
        error_message: str,
        cost_delta_usd: Decimal,
    ) -> ProductScanJob | None:
        now = datetime.now(timezone.utc)
        stmt = (
            update(ProductScanJob)
            .where(
                ProductScanJob.id == job_id,
                ProductScanJob.claimed_by == claimed_by,
            )
            .values(
                stage=SCAN_STAGE_FAILED,
                failed_at=now,
                last_heartbeat_at=now,
                claimed_by=None,
                lease_expires_at=None,
                error_code=error_code,
                error_message=error_message,
                cost_usd_estimate=(
                    ProductScanJob.cost_usd_estimate + cost_delta_usd
                ),
            )
            .returning(ProductScanJob)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def cancel(
        self,
        *,
        org_id: UUID,
        job_id: UUID,
    ) -> ProductScanJob | None:
        """User-triggered cancel.

        Marks the job ``cancelled``. The worker (if still running) sees
        the new stage on next heartbeat and bails out — mid-run
        cancellation is best-effort, not synchronous.
        """
        now = datetime.now(timezone.utc)
        stmt = (
            update(ProductScanJob)
            .where(
                ProductScanJob.id == job_id,
                ProductScanJob.org_id == org_id,
                ProductScanJob.stage.in_(list(ACTIVE_SCAN_STAGES)),
            )
            .values(
                stage=SCAN_STAGE_CANCELLED,
                cancelled_at=now,
                last_heartbeat_at=now,
            )
            .returning(ProductScanJob)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def advance_stage(
        self,
        *,
        job_id: UUID,
        claimed_by: str,
        stage: str,
    ) -> ProductScanJob | None:
        """Transition to a non-terminal stage (assembling / rendering)
        without changing lease or cost — used between worker phases.
        """
        if stage not in {SCAN_STAGE_ASSEMBLING, SCAN_STAGE_RENDERING}:
            raise ValueError(f"advance_stage refuses {stage!r}")
        stmt = (
            update(ProductScanJob)
            .where(
                ProductScanJob.id == job_id,
                ProductScanJob.claimed_by == claimed_by,
            )
            .values(stage=stage, last_heartbeat_at=datetime.now(timezone.utc))
            .returning(ProductScanJob)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # ------------------------------------------------------------------
    # Phase 4 wizard — scan-order parent + render-child helpers
    # ------------------------------------------------------------------

    async def create_scan_order_parent(
        self,
        *,
        org_id: UUID,
        video_id: UUID,
        user_id: UUID,
        length_seconds: int,
        requested_count: int,
        time_range_start_ms: int | None,
        time_range_end_ms: int | None,
        product_distribution: str,
        language: str,
        intent: str,
        settings_hash: str,
        catalog_entry_id: UUID | None = None,
    ) -> ProductScanJob:
        """Insert a wizard parent row.

        ``mode='scan_order'`` + every wizard input from the body. The
        DB-level CHECKs (``ck_psj_parent_required_fields``,
        ``ck_psj_aggregate_output``, etc.) catch any service-side
        validation gap.

        ``catalog_entry_id`` is NULL by default — parent processes the
        whole active catalog (legacy round-robin via the picker). When
        the wizard's product-select step returns a chosen entry, the
        service layer plumbs it through and the worker filters its
        catalog fetch to that single entry. The ``ck_psj_parent_*``
        constraints don't gate this column for scan_order parents.
        """
        job = ProductScanJob(
            org_id=org_id,
            video_id=video_id,
            requested_by_user_id=user_id,
            catalog_entry_id=catalog_entry_id,
            duration_preset_sec=length_seconds,  # legacy column carries the same number
            mode=SCAN_MODE_SCAN_ORDER,
            length_seconds=length_seconds,
            requested_count=requested_count,
            time_range_start_ms=time_range_start_ms,
            time_range_end_ms=time_range_end_ms,
            product_distribution=product_distribution,
            language=language,
            intent=intent,
            settings_hash=settings_hash,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def create_render_children(
        self,
        *,
        parent: ProductScanJob,
        count: int,
    ) -> list[ProductScanJob]:
        """Bulk insert N child rows for a scan_order parent.

        Children inherit ``org_id``, ``video_id``,
        ``requested_by_user_id``, and ``length_seconds`` from the
        parent. Each carries its own ``shorts_index`` (1..count) which
        the picker uses to spread products across shorts.
        """
        if parent.mode != SCAN_MODE_SCAN_ORDER:
            raise ValueError(
                f"cannot fan out children from non-scan_order parent "
                f"(parent.mode={parent.mode!r})"
            )
        if count < 1:
            raise ValueError(f"count must be >= 1, got {count!r}")
        children = [
            ProductScanJob(
                org_id=parent.org_id,
                video_id=parent.video_id,
                requested_by_user_id=parent.requested_by_user_id,
                catalog_entry_id=None,
                duration_preset_sec=parent.length_seconds,
                mode=SCAN_MODE_RENDER_CHILD,
                parent_job_id=parent.id,
                shorts_index=i,
                length_seconds=parent.length_seconds,
            )
            for i in range(1, count + 1)
        ]
        self.session.add_all(children)
        await self.session.flush()
        return children

    async def find_recent_scan_order_duplicate(
        self,
        *,
        org_id: UUID,
        user_id: UUID,
        settings_hash: str,
        within_seconds: int,
    ) -> ProductScanJob | None:
        """Wizard idempotency lookup — returns the existing parent
        row if (org, user, settings_hash) matches within window.

        Settings hash is canonical-JSON of every wizard input
        (computed in the service layer). ``intent`` is part of the
        hash, so preview and commit cannot dedupe each other.
        ``org_id`` is mandatory (mirrors the defensive fix on
        ``find_recent_duplicate``).
        """
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=within_seconds)
        stmt = (
            select(ProductScanJob)
            .where(
                ProductScanJob.org_id == org_id,
                ProductScanJob.requested_by_user_id == user_id,
                ProductScanJob.mode == SCAN_MODE_SCAN_ORDER,
                ProductScanJob.settings_hash == settings_hash,
                ProductScanJob.created_at >= cutoff,
            )
            .order_by(ProductScanJob.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def find_children_for_parent(
        self,
        *,
        org_id: UUID,
        parent_job_id: UUID,
    ) -> list[ProductScanJob]:
        """List a parent's children ordered by ``shorts_index``.
        Org-scoped — defense in depth (``parent_job_id`` is unique
        but the join keeps this query consistent with the rest of
        the module's tenant-scoping convention).
        """
        stmt = (
            select(ProductScanJob)
            .where(
                ProductScanJob.parent_job_id == parent_job_id,
                ProductScanJob.org_id == org_id,
                ProductScanJob.mode == SCAN_MODE_RENDER_CHILD,
            )
            .order_by(ProductScanJob.shorts_index.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def find_queued_render_children(
        self,
        *,
        limit: int,
    ) -> list[UUID]:
        """Runner poll query — returns at most ``limit`` queued
        ``mode='render_child'`` job ids ordered FIFO by created_at.

        Returns id-only to keep the row footprint small; the runner
        re-fetches via ``get_internal`` after a successful claim.
        Multi-replica safe: claim is the actual race resolver, not
        this poll.
        """
        stmt = (
            select(ProductScanJob.id)
            .where(
                ProductScanJob.mode == SCAN_MODE_RENDER_CHILD,
                ProductScanJob.stage == SCAN_STAGE_QUEUED,
            )
            .order_by(ProductScanJob.created_at.asc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def cancel_scan_order(
        self,
        *,
        org_id: UUID,
        parent_job_id: UUID,
    ) -> int:
        """Cascade-cancel a wizard order: parent + all non-terminal
        children. Returns the count of rows transitioned (parent
        included if it was active).

        Idempotent — already-terminal rows are skipped silently.
        """
        now = datetime.now(timezone.utc)
        # Parent: active stages only (so already-cancelled parents
        # don't re-trigger the timestamps).
        parent_stmt = (
            update(ProductScanJob)
            .where(
                ProductScanJob.id == parent_job_id,
                ProductScanJob.org_id == org_id,
                ProductScanJob.mode == SCAN_MODE_SCAN_ORDER,
                ProductScanJob.stage.in_(list(ACTIVE_SCAN_STAGES)),
            )
            .values(
                stage=SCAN_STAGE_CANCELLED,
                cancelled_at=now,
                last_heartbeat_at=now,
            )
        )
        parent_result = await self.session.execute(parent_stmt)
        # Children: cancel any non-terminal child of this parent.
        children_stmt = (
            update(ProductScanJob)
            .where(
                ProductScanJob.parent_job_id == parent_job_id,
                ProductScanJob.org_id == org_id,
                ProductScanJob.mode == SCAN_MODE_RENDER_CHILD,
                ProductScanJob.stage.notin_(list(TERMINAL_SCAN_STAGES)),
            )
            .values(
                stage=SCAN_STAGE_CANCELLED,
                cancelled_at=now,
                last_heartbeat_at=now,
            )
        )
        children_result = await self.session.execute(children_stmt)
        return (parent_result.rowcount or 0) + (children_result.rowcount or 0)

    async def get_scan_order_with_children(
        self,
        *,
        org_id: UUID,
        parent_job_id: UUID,
    ) -> tuple[ProductScanJob, list[ProductScanJob]] | None:
        """Aggregate read for ``GET /scan-orders/{parent_job_id}``.

        Two queries (parent + children) — pgsql window functions
        could pack this into one but the row count is bounded by
        ``requested_count`` (≤50) so the simpler shape wins.
        """
        parent = await self.get(org_id=org_id, job_id=parent_job_id)
        if parent is None or parent.mode != SCAN_MODE_SCAN_ORDER:
            return None
        children = await self.find_children_for_parent(
            org_id=org_id, parent_job_id=parent_job_id,
        )
        return parent, children
