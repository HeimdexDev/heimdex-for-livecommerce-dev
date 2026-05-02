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
    SCAN_STAGE_ASSEMBLING,
    SCAN_STAGE_CANCELLED,
    SCAN_STAGE_DONE,
    SCAN_STAGE_ENUMERATING,
    SCAN_STAGE_ENUMERATION_DONE,
    SCAN_STAGE_FAILED,
    SCAN_STAGE_QUEUED,
    SCAN_STAGE_RENDERING,
    SCAN_STAGE_TRACKING,
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
        if next_stage not in {SCAN_STAGE_ENUMERATING, SCAN_STAGE_TRACKING}:
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
