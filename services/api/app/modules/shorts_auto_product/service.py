"""ProductScanService — orchestration for shorts-auto product mode v2.

Public methods translate API requests into:
* DB writes via repositories,
* SQS publishes via :mod:`app.sqs_producer`,
* S3 presigned URL minting via :class:`app.storage.s3.S3Client`.

Pre-flight checks every public method runs (in this order):
1. Feature flag enabled + org in rollout bucket.
2. Daily cost cap (returns 402 if hit; in-flight jobs run to completion).
3. Per-org concurrency cap (returns 429 if hit).
4. Idempotency window (returns the existing job_id if matched).

The service does **not** import worker code or
``heimdex_media_pipelines``. Worker output reaches the service via
the :mod:`app.modules.shorts_auto_product.internal_router` callback
endpoints (Bearer-authed) which delegate persistence to the
repositories.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import sqs_producer
from app.config import Settings
from app.logging_config import get_logger
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
    ProductCatalogEntry,
    ProductScanJob,
)
from app.modules.shorts_auto_product.repositories import (
    ProductAppearanceRepository,
    ProductCatalogRepository,
    ProductScanDailyCostRepository,
    ProductScanJobRepository,
)
from app.modules.shorts_auto_product.schemas import (
    CatalogProductSummary,
    ClipResponse,
    DurationPresetSec,
    JobKind,
    JobStatusResponse,
    ProductCatalogResponse,
    ProductV2AvailabilityFragment,
    RescanResponse,
    ScanResponse,
    ScanStage,
    ScanStatus,
)

logger = get_logger(__name__)


# Presigned URL TTL for canonical product crops surfaced to the
# frontend gallery. Short — the gallery is browsed in seconds, not
# hours, and a long TTL widens the leak surface if the URL is shared.
_CROP_URL_TTL_SECONDS = 300


def _stable_org_bucket(org_id: UUID) -> int:
    """Hash org_id into [0, 100) for the rollout-percentage gate.

    Same pattern as ``auto_shorts_llm_rollout_pct``: stable across
    process restarts, no per-request randomness.
    """
    h = hashlib.sha256(str(org_id).encode("utf-8")).hexdigest()
    return int(h[:8], 16) % 100


class ProductScanService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        settings: Settings,
    ) -> None:
        self.session: AsyncSession = session
        self.settings: Settings = settings
        self.catalog_repo = ProductCatalogRepository(session)
        self.appearance_repo = ProductAppearanceRepository(session)
        self.job_repo = ProductScanJobRepository(session)
        self.cost_repo = ProductScanDailyCostRepository(session)

    # ------------------------------------------------------------------
    # gating helpers
    # ------------------------------------------------------------------

    def _require_enabled_for_org(self, org_id: UUID) -> None:
        """404 if v2 is off globally; 404 if this org is outside the
        rollout. We use 404 (not 403) so an org outside rollout sees
        the v1 product mode UI without leaking that v2 exists."""
        if not self.settings.auto_shorts_product_v2_enabled:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="product mode v2 is not enabled",
            )
        rollout = self.settings.auto_shorts_product_v2_rollout_pct
        if rollout < 100 and _stable_org_bucket(org_id) >= rollout:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="product mode v2 is not enabled for this org",
            )

    async def _require_budget(self, org_id: UUID) -> Decimal:
        """402 if today's cost exceeds the cap. Returns the running
        cost so the caller can include it in logs."""
        running = await self.cost_repo.get_today_cost(org_id=org_id)
        cap = Decimal(str(self.settings.auto_shorts_product_v2_daily_budget_usd))
        if running >= cap:
            logger.warning(
                "product_v2_cost_cap_reached",
                org_id=str(org_id),
                running_usd=str(running),
                cap_usd=str(cap),
            )
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="daily product-scan budget reached; resets at 00:00 UTC",
            )
        return running

    async def _require_concurrency_slot(self, org_id: UUID) -> None:
        active = await self.job_repo.count_active_for_org(org_id=org_id)
        cap = self.settings.auto_shorts_product_v2_max_concurrent_per_org
        if active >= cap:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"too many active product scans ({active}/{cap}); "
                    "wait for one to complete or cancel an in-flight job"
                ),
            )

    # ------------------------------------------------------------------
    # GET /products/{video_id}
    # ------------------------------------------------------------------

    async def list_products(
        self,
        *,
        org_id: UUID,
        video_id: UUID,
    ) -> ProductCatalogResponse:
        self._require_enabled_for_org(org_id)
        from app.storage.s3 import S3Client

        entries = await self.catalog_repo.list_active_by_video(
            org_id=org_id, video_id=video_id,
        )
        scan_status, scan_job_id = await self._resolve_scan_status(
            org_id=org_id, video_id=video_id, entries=entries,
        )

        s3 = S3Client(bucket=self.settings.drive_s3_bucket)
        products: list[CatalogProductSummary] = []
        for entry in entries:
            crop_url = await s3.generate_presigned_url_async(
                entry.canonical_crop_s3_key,
                expires_in=_CROP_URL_TTL_SECONDS,
            )
            appearance_count = await self.appearance_repo.count_active(
                org_id=org_id, catalog_entry_id=entry.id,
            )
            total_seconds: float | None = None
            if appearance_count > 0:
                appearances = await self.appearance_repo.list_active_by_catalog(
                    org_id=org_id, catalog_entry_id=entry.id,
                )
                total_seconds = sum(
                    (a.window_end_ms - a.window_start_ms) / 1000.0
                    for a in appearances
                )
            products.append(
                CatalogProductSummary(
                    catalog_entry_id=entry.id,
                    label=entry.user_label or entry.llm_label,
                    canonical_crop_url=crop_url,
                    enumeration_confidence=entry.enumeration_confidence,
                    prominence_score=entry.prominence_score,
                    has_track_data=appearance_count > 0,
                    appearance_count=appearance_count if appearance_count > 0 else None,
                    total_appearance_seconds=total_seconds,
                )
            )

        return ProductCatalogResponse(
            video_id=video_id,
            scan_status=scan_status,
            scan_job_id=scan_job_id,
            enumeration_version=(
                entries[0].enumeration_version if entries else None
            ),
            enumeration_prompt_version=(
                entries[0].enumeration_prompt_version if entries else None
            ),
            products=products,
        )

    async def _resolve_scan_status(
        self,
        *,
        org_id: UUID,
        video_id: UUID,
        entries: list[ProductCatalogEntry],
    ) -> tuple[ScanStatus, UUID | None]:
        # If we have entries, the most recent enumeration succeeded.
        # If we don't, fall back to the most recent enumeration job
        # for this (org, video) to distinguish "never scanned" vs
        # "in progress" vs "failed".
        if entries:
            return "complete", None
        # Org-scoped lookup so a second user opening the same video sees
        # "in progress" rather than "never scanned" while the first
        # user's job is mid-flight.
        most_recent = await self.job_repo.find_latest_enumeration_for_video(
            org_id=org_id, video_id=video_id,
        )
        if most_recent is None:
            return "never", None
        if most_recent.stage in ACTIVE_SCAN_STAGES:
            return "in_progress", most_recent.id
        if most_recent.stage == SCAN_STAGE_FAILED:
            return "failed", None
        return "never", None

    # ------------------------------------------------------------------
    # POST /products/{video_id}/scan
    # ------------------------------------------------------------------

    async def enqueue_scan(
        self,
        *,
        org_id: UUID,
        video_id: UUID,
        user_id: UUID,
        duration_preset_sec: DurationPresetSec,
    ) -> ScanResponse:
        self._require_enabled_for_org(org_id)
        await self._require_budget(org_id)

        # Idempotency: same (org, video, user) within window → return existing.
        # ``org_id`` is mandatory (codex defensive fix; see repositories/job.py).
        existing = await self.job_repo.find_recent_duplicate(
            org_id=org_id,
            video_id=video_id,
            user_id=user_id,
            catalog_entry_id=None,
            within_seconds=self.settings.auto_shorts_product_v2_scan_idempotency_seconds,
        )
        if existing is not None:
            return ScanResponse(job_id=existing.id, deduped=True)

        await self._require_concurrency_slot(org_id)

        job = await self.job_repo.create_enumeration_job(
            org_id=org_id,
            video_id=video_id,
            user_id=user_id,
            duration_preset_sec=duration_preset_sec,
        )
        await self.session.flush()

        try:
            sqs_producer.publish_product_enumerate_job(
                job_id=job.id,
                org_id=org_id,
                video_id=video_id,
                requested_by_user_id=user_id,
                enumeration_version=self.settings.auto_shorts_product_v2_enumeration_version,
                enumeration_prompt_version=self.settings.auto_shorts_product_v2_enumeration_prompt_version,
                max_keyframes=self.settings.auto_shorts_product_v2_max_keyframes_per_video,
                callback_base_url=self.settings.auto_shorts_product_v2_callback_base_url,
            )
        except Exception:
            logger.exception(
                "product_v2_enumerate_publish_failed",
                job_id=str(job.id),
                org_id=str(org_id),
            )
            await self.job_repo.fail(
                job_id=job.id,
                claimed_by="api",
                error_code="internal_error",
                error_message="failed to enqueue scan; please retry",
                cost_delta_usd=Decimal("0"),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="failed to enqueue scan; please retry",
            )

        logger.info(
            "product_v2_scan_enqueued",
            job_id=str(job.id),
            org_id=str(org_id),
            video_id=str(video_id),
            user_id=str(user_id),
            duration_preset_sec=duration_preset_sec,
        )
        return ScanResponse(job_id=job.id, deduped=False)

    # ------------------------------------------------------------------
    # POST /products/{video_id}/{catalog_entry_id}/clip
    # ------------------------------------------------------------------

    async def enqueue_clip(
        self,
        *,
        org_id: UUID,
        video_id: UUID,
        catalog_entry_id: UUID,
        user_id: UUID,
        duration_preset_sec: DurationPresetSec,
    ) -> ClipResponse:
        self._require_enabled_for_org(org_id)
        await self._require_budget(org_id)

        # Verify the catalog entry exists and belongs to this org/video.
        entry = await self.catalog_repo.get(org_id=org_id, entry_id=catalog_entry_id)
        if entry is None or entry.video_id != video_id or entry.rejected_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="catalog entry not found",
            )

        existing = await self.job_repo.find_recent_duplicate(
            org_id=org_id,
            video_id=video_id,
            user_id=user_id,
            catalog_entry_id=catalog_entry_id,
            within_seconds=self.settings.auto_shorts_product_v2_scan_idempotency_seconds,
        )
        if existing is not None:
            return ClipResponse(
                job_id=existing.id,
                deduped=True,
                render_job_id=existing.render_job_id,
            )

        await self._require_concurrency_slot(org_id)

        job = await self.job_repo.create_tracking_job(
            org_id=org_id,
            video_id=video_id,
            user_id=user_id,
            catalog_entry_id=catalog_entry_id,
            duration_preset_sec=duration_preset_sec,
        )
        await self.session.flush()

        try:
            sqs_producer.publish_product_track_job(
                job_id=job.id,
                org_id=org_id,
                video_id=video_id,
                catalog_entry_id=catalog_entry_id,
                requested_by_user_id=user_id,
                duration_preset_sec=duration_preset_sec,
                tracker_version=self.settings.auto_shorts_product_v2_tracker_version,
                enumeration_prompt_version=self.settings.auto_shorts_product_v2_enumeration_prompt_version,
                callback_base_url=self.settings.auto_shorts_product_v2_callback_base_url,
            )
        except Exception:
            logger.exception(
                "product_v2_track_publish_failed",
                job_id=str(job.id),
                catalog_entry_id=str(catalog_entry_id),
            )
            await self.job_repo.fail(
                job_id=job.id,
                claimed_by="api",
                error_code="internal_error",
                error_message="failed to enqueue clip; please retry",
                cost_delta_usd=Decimal("0"),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="failed to enqueue clip; please retry",
            )

        logger.info(
            "product_v2_clip_enqueued",
            job_id=str(job.id),
            catalog_entry_id=str(catalog_entry_id),
            duration_preset_sec=duration_preset_sec,
        )
        return ClipResponse(job_id=job.id, deduped=False)

    # ------------------------------------------------------------------
    # GET /jobs/{job_id}
    # ------------------------------------------------------------------

    async def get_job_status(
        self,
        *,
        org_id: UUID,
        job_id: UUID,
    ) -> JobStatusResponse:
        self._require_enabled_for_org(org_id)
        job = await self.job_repo.get(org_id=org_id, job_id=job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="job not found",
            )
        return _job_to_status_response(job)

    # ------------------------------------------------------------------
    # POST /jobs/{job_id}/cancel
    # ------------------------------------------------------------------

    async def cancel_job(
        self,
        *,
        org_id: UUID,
        job_id: UUID,
    ) -> None:
        self._require_enabled_for_org(org_id)
        cancelled = await self.job_repo.cancel(org_id=org_id, job_id=job_id)
        if cancelled is None:
            # Either no such job, wrong org, or already terminal —
            # 404 in all three cases (no info leak between them).
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="job not found or already terminal",
            )

    # ------------------------------------------------------------------
    # DELETE /products/{video_id}/{catalog_entry_id}
    # ------------------------------------------------------------------

    async def reject_catalog_entry(
        self,
        *,
        org_id: UUID,
        video_id: UUID,
        catalog_entry_id: UUID,
        reason: str = "admin_reject",
    ) -> None:
        self._require_enabled_for_org(org_id)
        entry = await self.catalog_repo.get(
            org_id=org_id, entry_id=catalog_entry_id,
        )
        if entry is None or entry.video_id != video_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="catalog entry not found",
            )
        ok = await self.catalog_repo.soft_reject(
            org_id=org_id, entry_id=catalog_entry_id, reason=reason,
        )
        if not ok:
            # Already rejected — idempotent.
            return

    # ------------------------------------------------------------------
    # POST /products/{video_id}/rescan
    # ------------------------------------------------------------------

    async def rescan(
        self,
        *,
        org_id: UUID,
        video_id: UUID,
        user_id: UUID,
        duration_preset_sec: DurationPresetSec,
    ) -> RescanResponse:
        self._require_enabled_for_org(org_id)
        await self._require_budget(org_id)
        await self._require_concurrency_slot(org_id)

        invalidated = await self.catalog_repo.invalidate_video_catalog(
            org_id=org_id, video_id=video_id, reason="rescan_invalidated",
        )

        job = await self.job_repo.create_enumeration_job(
            org_id=org_id,
            video_id=video_id,
            user_id=user_id,
            duration_preset_sec=duration_preset_sec,
        )
        await self.session.flush()

        try:
            sqs_producer.publish_product_enumerate_job(
                job_id=job.id,
                org_id=org_id,
                video_id=video_id,
                requested_by_user_id=user_id,
                enumeration_version=self.settings.auto_shorts_product_v2_enumeration_version,
                enumeration_prompt_version=self.settings.auto_shorts_product_v2_enumeration_prompt_version,
                max_keyframes=self.settings.auto_shorts_product_v2_max_keyframes_per_video,
                callback_base_url=self.settings.auto_shorts_product_v2_callback_base_url,
            )
        except Exception:
            logger.exception(
                "product_v2_rescan_publish_failed",
                job_id=str(job.id),
                org_id=str(org_id),
            )
            await self.job_repo.fail(
                job_id=job.id, claimed_by="api",
                error_code="internal_error",
                error_message="failed to enqueue rescan; please retry",
                cost_delta_usd=Decimal("0"),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="failed to enqueue rescan; please retry",
            )

        return RescanResponse(job_id=job.id, invalidated_count=invalidated)

    # ------------------------------------------------------------------
    # availability fragment
    # ------------------------------------------------------------------

    async def availability_fragment(
        self,
        *,
        org_id: UUID,
    ) -> ProductV2AvailabilityFragment:
        in_rollout = (
            self.settings.auto_shorts_product_v2_enabled
            and (
                self.settings.auto_shorts_product_v2_rollout_pct >= 100
                or _stable_org_bucket(org_id)
                < self.settings.auto_shorts_product_v2_rollout_pct
            )
        )
        running = await self.cost_repo.get_today_cost(org_id=org_id)
        cap = Decimal(str(self.settings.auto_shorts_product_v2_daily_budget_usd))
        if cap <= 0:
            remaining_pct = 0
        else:
            remaining_pct = max(0, min(100, int(((cap - running) / cap) * 100)))
        presets = [
            int(p.strip())
            for p in self.settings.auto_shorts_product_v2_duration_presets_sec.split(",")
            if p.strip()
        ]
        return ProductV2AvailabilityFragment(
            product_v2_enabled=self.settings.auto_shorts_product_v2_enabled,
            product_v2_in_rollout=in_rollout,
            product_v2_daily_budget_remaining_pct=remaining_pct,
            product_v2_duration_presets_sec=presets,
        )


# ---------- helpers ----------

def _job_to_status_response(job: ProductScanJob) -> JobStatusResponse:
    """Mode-aware projection of a ``ProductScanJob`` to the public
    ``JobStatusResponse`` shape.

    Discriminator switch (Phase 4 task #1, codex-flagged): branches on
    ``job.mode`` rather than the pre-Phase-4 ``catalog_entry_id IS NULL``
    heuristic, which would misclassify ``mode='scan_order'`` parents
    (also NULL) as enumeration jobs.

    Q4 codex pushback: ``render_job_id`` is forced to ``None`` for
    ``mode='scan_order'`` parents in the response payload, even if the
    row somehow carries one (the ``ck_psj_parent_no_render`` CHECK
    should make that impossible at the DB level). Defense in depth:
    every layer agrees parents do not carry render FKs.
    """
    from app.modules.shorts_auto_product.models import (
        SCAN_MODE_ENUMERATE,
        SCAN_MODE_RENDER_CHILD,
        SCAN_MODE_SCAN_ORDER,
    )

    if job.mode == SCAN_MODE_SCAN_ORDER:
        kind: JobKind = "scan_order"
        # Defensive: parents must not echo a render_job_id even if the
        # row carries one. CHECK constraint prevents writes; this is
        # belt-and-suspenders for the read path.
        render_job_id_response: UUID | None = None
    elif job.mode == SCAN_MODE_RENDER_CHILD:
        kind = "render_child"
        render_job_id_response = job.render_job_id
    elif job.mode == SCAN_MODE_ENUMERATE:
        # Backward compat: the dispatch from ``mode='enumerate'`` to
        # the user-facing kind still depends on ``catalog_entry_id``
        # during the +4wk legacy ``enqueue_clip`` deprecation window.
        if job.catalog_entry_id is not None:
            kind = "tracking"  # legacy single-product flow
        else:
            kind = "enumeration"
        render_job_id_response = job.render_job_id
    else:  # pragma: no cover — CHECK constraint forbids other values
        raise ValueError(f"unknown ProductScanJob.mode: {job.mode!r}")

    stage: ScanStage = job.stage  # type: ignore[assignment]
    error_code = job.error_code  # type: ignore[assignment]
    return JobStatusResponse(
        job_id=job.id,
        kind=kind,
        stage=stage,
        progress_pct=job.progress_pct,
        progress_label=job.progress_label,
        completed_at=job.completed_at,
        failed_at=job.failed_at,
        cancelled_at=job.cancelled_at,
        error_code=error_code,
        error_message=job.error_message,
        render_job_id=render_job_id_response,
        parent_job_id=job.parent_job_id,
        shorts_index=job.shorts_index,
        cost_usd_estimate=job.cost_usd_estimate,
    )
