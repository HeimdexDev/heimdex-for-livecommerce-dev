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
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
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
    SCAN_STAGE_FANNED_OUT,
    SCAN_STAGE_QUEUED,
    SCAN_STAGE_RENDERING,
    SCAN_STAGE_TRACKING,
    TERMINAL_SCAN_STAGES,
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
    ScanOrderCreateRequest,
    ScanOrderResponse,
    ScanOrderStatusResponse,
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
            # Distinguish "scan ran cleanly but found nothing" from
            # "scan crashed". Prior bug: every failed enumeration
            # mapped to scan_status='failed', which the wizard
            # surfaced as "이전 스캔이 실패했어요. 다시 시도해 주세요"
            # — telling the user to retry on a video the LLM had
            # already correctly classified as having no detectable
            # products. Caught while testing on
            # gd_907a1b5c8cdf5bb5 (a banner-heavy intro masked the
            # host-with-product moments deeper in the video).
            #
            # ``no_products_detected`` is the worker's terminal-but-
            # benign outcome (LLM ran end-to-end and clustered nothing
            # above the noise floor). Map it to ``complete`` so the
            # wizard renders the "no products in this video" UX
            # (matching the empty-catalog branch) rather than the
            # retry-please surface. All other error_codes (timeouts,
            # schema errors, internal_error) stay as ``failed``.
            if most_recent.error_code == "no_products_detected":
                return "complete", None
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

    # ------------------------------------------------------------------
    # Phase 4 wizard — scan-order endpoints
    # ------------------------------------------------------------------

    async def enqueue_scan_order(
        self,
        *,
        org_id: UUID,
        video_id: UUID,
        user_id: UUID,
        body: ScanOrderCreateRequest,
    ) -> ScanOrderResponse:
        """Create a wizard parent job from the 4-step wizard inputs.

        Pre-flight order matches the rest of this service (flag,
        budget, idempotency, concurrency). Aggregate-output cap is
        enforced both as a 422 here and as a DB CHECK
        (``ck_psj_aggregate_output``) — service-layer 422 gives a
        meaningful error message before the row hits Postgres.

        SQS publish for ``mode='scan_order'`` parents is wired in PR #3
        alongside the worker refactor. Until then, parent rows persist
        in stage='queued' but no worker consumes them — so the wizard
        flow end-to-end requires PR #3 to land before the parent
        actually progresses past 'queued'. This is intentional: it
        keeps PR #2 testable in isolation without DLQ noise from the
        existing track-worker rejecting the new mode.
        """
        self._require_enabled_for_org(org_id)
        await self._require_budget(org_id)

        # Service-layer validation that complements the DB CHECKs with
        # better error messages for the frontend.
        _validate_scan_order_inputs(body=body)

        # If the wizard's product-select step picked a specific entry,
        # validate it BEFORE allocating a concurrency slot — same shape
        # as the legacy ``enqueue_clip`` 404 (no-info-leak: cross-org,
        # missing, and rejected all return the same status). The check
        # also doubles as a defense against stale catalog ids that
        # survived a rescan invalidation.
        if body.catalog_entry_id is not None:
            entry = await self.catalog_repo.get(
                org_id=org_id, entry_id=body.catalog_entry_id,
            )
            if (
                entry is None
                or entry.video_id != video_id
                or entry.rejected_at is not None
            ):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="catalog entry not found",
                )

        # Active catalog set drives idempotency invalidation: a rescan
        # that produces new entries naturally invalidates the dedupe
        # key without needing an explicit catalog version column.
        active_entries = await self.catalog_repo.list_active_by_video(
            org_id=org_id, video_id=video_id,
        )
        active_entry_ids = sorted(str(e.id) for e in active_entries)

        settings_hash = compute_settings_hash(
            video_id=video_id,
            user_id=user_id,
            length_seconds=body.length_seconds,
            requested_count=body.requested_count,
            time_range_start_ms=body.time_range_start_ms,
            time_range_end_ms=body.time_range_end_ms,
            product_distribution=body.product_distribution,
            language=body.language,
            intent=body.intent,
            active_catalog_entry_ids=active_entry_ids,
            tracker_version=self.settings.auto_shorts_product_v2_tracker_version,
            enumeration_prompt_version=(
                self.settings.auto_shorts_product_v2_enumeration_prompt_version
            ),
            selected_catalog_entry_id=(
                str(body.catalog_entry_id)
                if body.catalog_entry_id is not None
                else None
            ),
        )

        existing = await self.job_repo.find_recent_scan_order_duplicate(
            org_id=org_id,
            user_id=user_id,
            settings_hash=settings_hash,
            within_seconds=(
                self.settings.auto_shorts_product_v2_scan_order_idempotency_seconds
            ),
        )
        if existing is not None:
            return ScanOrderResponse(
                parent_job_id=existing.id, deduped=True,
            )

        await self._require_concurrency_slot(org_id)

        parent = await self.job_repo.create_scan_order_parent(
            org_id=org_id,
            video_id=video_id,
            user_id=user_id,
            length_seconds=body.length_seconds,
            requested_count=body.requested_count,
            time_range_start_ms=body.time_range_start_ms,
            time_range_end_ms=body.time_range_end_ms,
            product_distribution=body.product_distribution,
            language=body.language,
            intent=body.intent,
            settings_hash=settings_hash,
            catalog_entry_id=body.catalog_entry_id,
        )
        await self.session.flush()

        # PR 2.6 STT-pivot: when track_mode='stt', skip the SQS
        # publish entirely (the SAM2 product-track-worker is the
        # consumer of that queue) and fan out children inline. The
        # api-process child runner (PR 2.5) picks up the children
        # via the queued-render_children poll and runs the in-process
        # STT pipeline.
        #
        # Without this branch, a track_mode='stt' scan_order races
        # the still-deployed SAM2 worker which claims the SQS message
        # first and runs SAM2 tracking — exactly what the STT pivot
        # is replacing. See plan §"PR 2.6 — inline fan-out for STT mode"
        # for the full sequencing.
        track_mode = getattr(
            self.settings, "auto_shorts_product_v2_track_mode", "sam2",
        )
        if track_mode == "stt":
            await self.job_repo.create_render_children(
                parent=parent, count=body.requested_count,
            )
            await self.job_repo.transition_parent_to_fanned_out_unclaimed(
                job_id=parent.id,
            )
            logger.info(
                "product_v2_scan_order_stt_fanout",
                parent_job_id=str(parent.id),
                org_id=str(org_id),
                child_count=body.requested_count,
            )
        # Phase 4 PR — publish the parent track job to SQS so the
        # product-track-worker picks it up and runs the per-catalog
        # tracking loop. Gated on
        # ``auto_shorts_product_v2_publish_scan_order_enabled`` so we
        # can deploy the API code BEFORE the worker is rebuilt with
        # v0.14.0 contracts. Flipping the flag without the worker
        # ready would fill the worker DLQ with unparseable messages
        # (extra='forbid' rejects the new wizard fields on a v0.13.0
        # contracts pin).
        elif self.settings.auto_shorts_product_v2_publish_scan_order_enabled:
            try:
                sqs_producer.publish_product_track_job(
                    job_id=parent.id,
                    org_id=org_id,
                    video_id=video_id,
                    requested_by_user_id=user_id,
                    tracker_version=(
                        self.settings.auto_shorts_product_v2_tracker_version
                    ),
                    enumeration_prompt_version=(
                        self.settings
                        .auto_shorts_product_v2_enumeration_prompt_version
                    ),
                    callback_base_url=(
                        self.settings.auto_shorts_product_v2_callback_base_url
                    ),
                    mode="scan_order",
                    length_seconds=body.length_seconds,
                    requested_count=body.requested_count,
                    time_range_start_ms=body.time_range_start_ms,
                    time_range_end_ms=body.time_range_end_ms,
                    product_distribution=body.product_distribution,
                    language=body.language,
                    intent=body.intent,
                    # Optional pre-tracking pick. None = whole-catalog
                    # round-robin (legacy scan_order behavior). Set =
                    # worker filters its catalog fetch to this single
                    # entry. ``duration_preset_sec`` stays omitted —
                    # scan_order uses ``length_seconds`` not the legacy
                    # preset.
                    catalog_entry_id=body.catalog_entry_id,
                )
            except Exception:
                logger.exception(
                    "product_v2_scan_order_publish_failed",
                    parent_job_id=str(parent.id),
                    org_id=str(org_id),
                )
                # Mark the parent failed so the wizard UI can render a
                # retry affordance. The DB row already exists; failing
                # here matches the legacy enqueue_scan / enqueue_clip
                # error-handling shape.
                await self.job_repo.fail(
                    job_id=parent.id,
                    claimed_by="api",
                    error_code="internal_error",
                    error_message="failed to enqueue scan order; please retry",
                    cost_delta_usd=Decimal("0"),
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="failed to enqueue scan order; please retry",
                )

        logger.info(
            "product_v2_scan_order_created",
            parent_job_id=str(parent.id),
            org_id=str(org_id),
            video_id=str(video_id),
            user_id=str(user_id),
            length_seconds=body.length_seconds,
            requested_count=body.requested_count,
            distribution=body.product_distribution,
            language=body.language,
            intent=body.intent,
            settings_hash=settings_hash,
            published=(
                track_mode != "stt"
                and self.settings.auto_shorts_product_v2_publish_scan_order_enabled
            ),
            track_mode=track_mode,
        )
        return ScanOrderResponse(parent_job_id=parent.id, deduped=False)

    async def get_scan_order_status(
        self,
        *,
        org_id: UUID,
        parent_job_id: UUID,
    ) -> ScanOrderStatusResponse:
        """Aggregate read for the wizard's polling subscription."""
        self._require_enabled_for_org(org_id)
        result = await self.job_repo.get_scan_order_with_children(
            org_id=org_id, parent_job_id=parent_job_id,
        )
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="scan order not found",
            )
        parent, children = result

        # Lazy parent → committed transition.
        #
        # In the SAM2 SQS flow the worker's terminal callback could
        # carry the parent transition along; the STT inline path
        # (PR 2.6) has no such callback — children terminate via the
        # api-process runner and there is no follow-up that promotes
        # the parent to ``committed``. Without this lazy check the
        # parent stays at ``fanned_out`` forever and the wizard's
        # polling subscription never sees a terminal state.
        #
        # Trigger conditions:
        #   - parent.stage == fanned_out
        #   - children list non-empty (defensive — should always be
        #     so for fanned_out parents)
        #   - every child stage is in TERMINAL_SCAN_STAGES
        # Atomically guarded inside the repo method (only the first
        # racing caller wins). On race-loss the caller falls through
        # and the next poll sees the already-transitioned parent.
        if (
            parent.stage == SCAN_STAGE_FANNED_OUT
            and children
            and all(
                c.stage in TERMINAL_SCAN_STAGES for c in children
            )
        ):
            transitioned = await self.job_repo.transition_parent_to_committed_unclaimed(
                job_id=parent.id,
            )
            if transitioned is not None:
                parent = transitioned

        children_responses = [_job_to_status_response(c) for c in children]
        complete_count = sum(
            1 for c in children_responses if c.completed_at is not None
        )
        failed_count = sum(
            1 for c in children_responses
            if c.failed_at is not None or c.cancelled_at is not None
        )
        return ScanOrderStatusResponse(
            parent=_job_to_status_response(parent),
            children=children_responses,
            children_complete=complete_count,
            children_failed=failed_count,
            children_total=len(children_responses),
        )

    async def cancel_scan_order(
        self,
        *,
        org_id: UUID,
        parent_job_id: UUID,
    ) -> None:
        """Cascade-cancel a parent + its non-terminal children.

        404 if parent is missing OR not a scan_order OR no rows were
        transitioned (already-terminal cases hit the latter — same
        no-info-leak shape as the legacy ``cancel_job``).
        """
        self._require_enabled_for_org(org_id)
        # Verify the parent exists and is a scan_order before
        # attempting the cascade — keeps 404 semantics tight.
        parent = await self.job_repo.get(
            org_id=org_id, job_id=parent_job_id,
        )
        if parent is None or parent.mode != "scan_order":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="scan order not found",
            )
        rows_changed = await self.job_repo.cancel_scan_order(
            org_id=org_id, parent_job_id=parent_job_id,
        )
        if rows_changed == 0:
            # Parent + all children already terminal — idempotent
            # 404 same as the legacy cancel.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="scan order not found or already terminal",
            )

    async def commit_scan_order(
        self,
        *,
        org_id: UUID,
        parent_job_id: UUID,
        selected_window_ids: list[UUID] | None,
    ) -> None:
        """Phase 6 endpoint — preview → commit transition. Stubbed
        until the preview flow lands. Body shape locked now so the
        frontend wizard can be built against a stable contract.
        """
        self._require_enabled_for_org(org_id)
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="scan order commit is a Phase 6 deliverable",
        )


# ---------- helpers ----------


def compute_settings_hash(
    *,
    video_id: UUID,
    user_id: UUID,
    length_seconds: int,
    requested_count: int,
    time_range_start_ms: int | None,
    time_range_end_ms: int | None,
    product_distribution: str,
    language: str,
    intent: str,
    active_catalog_entry_ids: list[str],
    tracker_version: str,
    enumeration_prompt_version: str,
    selected_catalog_entry_id: str | None = None,
) -> str:
    """Canonical-JSON SHA256 of every wizard input that should
    discriminate "same intent" from "different intent" for the 60s
    idempotency window.

    Why these fields, codex-reviewed (plan §19 Q3):

    * ``video_id`` + ``user_id``: tenant-scoping happens at the SQL
      level via the ``find_recent_scan_order_duplicate`` filter, but
      including them in the hash makes the hash cross-tenant unique
      so cache poisoning via ID collision is impossible.
    * ``intent``: separates preview-flow dedupe from commit-flow
      dedupe — same wizard inputs in preview mode must not dedupe a
      subsequent commit.
    * ``active_catalog_entry_ids``: rescan that produces new entries
      naturally changes the hash → new parent. No catalog-version
      column needed.
    * ``tracker_version`` + ``enumeration_prompt_version``: model
      bumps invalidate dedupe correctly, so the user re-running with
      the same wizard inputs after a model deploy gets fresh output
      (otherwise the cached parent would be stuck on the old model).

    Canonical-JSON via ``sort_keys=True`` + tightest separators so
    the hash is stable across Python versions / dict ordering /
    unicode differences. NEVER change the hash composition without
    bumping this function's name; otherwise rolling deploys would
    miss caches across replicas mid-deploy.
    """
    payload: dict[str, Any] = {
        "video_id": str(video_id),
        "user_id": str(user_id),
        "intent": intent,
        "length_seconds": length_seconds,
        "requested_count": requested_count,
        "time_range_start_ms": time_range_start_ms or 0,
        "time_range_end_ms": time_range_end_ms or 0,
        "product_distribution": product_distribution,
        "language": language,
        "catalog_entry_ids": list(active_catalog_entry_ids),
        "tracker_version": tracker_version,
        "enumeration_prompt_version": enumeration_prompt_version,
    }
    # Only include the user's pick when set, so the no-pick path
    # preserves the original hash composition. Different picks for the
    # same video naturally get different hashes; flipping from no-pick
    # to a specific pick also re-hashes (intentional — semantically
    # different jobs).
    if selected_catalog_entry_id is not None:
        payload["selected_catalog_entry_id"] = selected_catalog_entry_id
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_scan_order_inputs(*, body: ScanOrderCreateRequest) -> None:
    """Service-layer validation that the DB CHECKs back-stop.

    Pydantic already enforces 10..120 length and 1..50 count via Field
    bounds. The DB enforces ``count * length <= 1800`` and
    time-range monotonicity. This function adds the 422s the
    frontend can render as inline errors:

      * aggregate output cap (count * length <= 1800)
      * time-range sanity: each short has at least its length in
        source range
    """
    aggregate_output_seconds = body.requested_count * body.length_seconds
    if aggregate_output_seconds > 1800:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"requested_count ({body.requested_count}) * length_seconds "
                f"({body.length_seconds}) = {aggregate_output_seconds}s exceeds "
                f"the 1800s (30 min) aggregate cap per scan order"
            ),
        )
    if (body.time_range_start_ms is None) != (body.time_range_end_ms is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "time_range_start_ms and time_range_end_ms must both be "
                "set or both be null"
            ),
        )
    if body.time_range_start_ms is not None and body.time_range_end_ms is not None:
        if body.time_range_end_ms <= body.time_range_start_ms:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="time_range_end_ms must be greater than time_range_start_ms",
            )
        span_ms = body.time_range_end_ms - body.time_range_start_ms
        per_short_budget_ms = span_ms / body.requested_count
        required_per_short_ms = body.length_seconds * 1000
        if per_short_budget_ms < required_per_short_ms:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"time range ({span_ms}ms) split across {body.requested_count} "
                    f"shorts gives only {int(per_short_budget_ms)}ms per short — "
                    f"each short needs at least {required_per_short_ms}ms of source"
                ),
            )

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
