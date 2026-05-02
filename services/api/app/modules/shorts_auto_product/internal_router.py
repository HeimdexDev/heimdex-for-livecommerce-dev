"""Internal worker callbacks for shorts-auto product mode v2.

Auth is the shared ``DRIVE_INTERNAL_API_KEY`` via
``verify_internal_token`` — the same Bearer the blur worker uses.
This router is only reachable from inside the VPC over the internal
service network.

Four endpoints, mirroring the contracts message types:

* ``POST /internal/products/{job_id}/claim`` — atomic transition
  ``queued → enumerating | tracking`` and lease grant.
* ``POST /internal/products/{job_id}/heartbeat`` — extend lease,
  advance progress, accumulate cost.
* ``POST /internal/products/{job_id}/complete`` — terminal success.
  Persists catalog entries (enum) or appearances + render_job_id
  (track).
* ``POST /internal/products/{job_id}/fail`` — terminal failure.

All write paths assert ``claimed_by`` matches the row so a stale
worker whose lease expired and was re-claimed cannot overwrite the
new owner.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.base import get_db_session
from app.dependencies import verify_internal_token
from app.modules.shorts_auto_product.models import (
    ACTIVE_SCAN_STAGES,
    SCAN_STAGE_ASSEMBLING,
    SCAN_STAGE_ENUMERATING,
    SCAN_STAGE_RENDERING,
    SCAN_STAGE_TRACKING,
)
from app.modules.shorts_auto_product.repositories import (
    ProductAppearanceRepository,
    ProductCatalogRepository,
    ProductScanDailyCostRepository,
    ProductScanJobRepository,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/products", tags=["internal-shorts-auto-product"])


# ---------- claim ----------

class _ClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claimed_by: str = Field(..., min_length=1, max_length=200)
    next_stage: Literal["enumerating", "tracking"]
    lease_seconds: int = Field(..., ge=60, le=3600)


class _ClaimResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: UUID
    org_id: UUID
    video_id: UUID
    catalog_entry_id: UUID | None
    duration_preset_sec: int
    stage: str
    lease_expires_at: datetime


@router.post("/{job_id}/claim", response_model=_ClaimResponse)
async def claim_job(
    job_id: UUID,
    body: _ClaimRequest,
    _token: Annotated[str, Depends(verify_internal_token)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> _ClaimResponse:
    repo = ProductScanJobRepository(db)
    job = await repo.claim(
        job_id=job_id,
        claimed_by=body.claimed_by,
        lease_seconds=body.lease_seconds,
        next_stage=body.next_stage,
    )
    if job is None:
        # Already claimed / completed / cancelled — worker should
        # treat as no-op and ack the SQS message. 409 is the right
        # signal here (not 404) so the worker can distinguish from a
        # genuinely-missing job.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="job is not in queued state",
        )
    await db.commit()
    return _ClaimResponse(
        job_id=job.id,
        org_id=job.org_id,
        video_id=job.video_id,
        catalog_entry_id=job.catalog_entry_id,
        duration_preset_sec=job.duration_preset_sec,
        stage=job.stage,
        lease_expires_at=job.lease_expires_at,  # type: ignore[arg-type]
    )


# ---------- heartbeat ----------

class _HeartbeatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claimed_by: str = Field(..., min_length=1, max_length=200)
    stage: Literal[
        "enumerating", "enumeration_done",
        "tracking", "assembling", "rendering",
    ]
    progress_pct: int = Field(..., ge=0, le=100)
    progress_label: str | None = Field(default=None, max_length=200)
    cost_delta_usd: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    lease_seconds: int = Field(..., ge=60, le=3600)


class _HeartbeatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lease_expires_at: datetime
    cancelled: bool


@router.post("/{job_id}/heartbeat", response_model=_HeartbeatResponse)
async def heartbeat(
    job_id: UUID,
    body: _HeartbeatRequest,
    _token: Annotated[str, Depends(verify_internal_token)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> _HeartbeatResponse:
    repo = ProductScanJobRepository(db)
    cost_repo = ProductScanDailyCostRepository(db)

    # Pre-check: was the user-side cancel triggered? Then we skip the
    # write so the cancelled stage stays terminal.
    existing = await repo.get_internal(job_id=job_id)
    if existing is None or existing.claimed_by != body.claimed_by:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="lease lost or job missing",
        )
    if existing.stage not in ACTIVE_SCAN_STAGES:
        # Most likely the user cancelled. Tell the worker so it can
        # bail out gracefully on its next loop.
        return _HeartbeatResponse(
            lease_expires_at=datetime.now(timezone.utc),
            cancelled=True,
        )

    updated = await repo.heartbeat(
        job_id=job_id,
        claimed_by=body.claimed_by,
        stage=body.stage,
        progress_pct=body.progress_pct,
        progress_label=body.progress_label,
        cost_delta_usd=body.cost_delta_usd,
        lease_seconds=body.lease_seconds,
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="lease lost mid-update",
        )

    if body.cost_delta_usd > Decimal("0"):
        await cost_repo.add_cost(
            org_id=existing.org_id, delta_usd=body.cost_delta_usd,
        )

    await db.commit()
    return _HeartbeatResponse(
        lease_expires_at=updated.lease_expires_at,  # type: ignore[arg-type]
        cancelled=False,
    )


# ---------- complete ----------

class _BBoxXYWH(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: int = Field(..., ge=0)
    y: int = Field(..., ge=0)
    w: int = Field(..., gt=0)
    h: int = Field(..., gt=0)


class _CatalogEntryPayload(BaseModel):
    """Worker-side ``ProductCatalogEntry`` projection for the
    complete callback. Mirrors
    :class:`heimdex_media_contracts.product.ProductCatalogEntry` but
    we redefine here to keep the router import-light (contracts can
    drift in lockstep without the API needing to bump pins)."""

    model_config = ConfigDict(extra="forbid")
    canonical_crop_s3_key: str = Field(..., min_length=1)
    canonical_video_id: UUID
    canonical_frame_idx: int = Field(..., ge=0)
    canonical_bbox: _BBoxXYWH
    llm_label: str = Field(..., min_length=1, max_length=200)
    siglip2_embedding: list[float] = Field(..., min_length=768, max_length=768)
    enumeration_confidence: float = Field(..., ge=0.0, le=1.0)
    prominence_score: float = Field(..., ge=0.0, le=1.0)
    enumeration_version: str = Field(..., min_length=1)
    enumeration_prompt_version: str = Field(..., min_length=1)


class _AppearancePayload(BaseModel):
    """Per-appearance shape for the ``/complete`` callback.

    For legacy single-product tracking jobs (``mode='enumerate'`` AND
    ``catalog_entry_id IS NOT NULL``), ``catalog_entry_id`` is derived
    server-side from the job row and MUST be omitted (or null) here —
    the worker doesn't carry it on the wire.

    For wizard scan_order parents (``mode='scan_order'``), the parent
    processed the whole catalog so each appearance row carries its own
    ``catalog_entry_id``. Required in this case; the dispatch path
    below 422s if missing.
    """

    model_config = ConfigDict(extra="forbid")
    # Optional on the wire; required-by-mode in the /complete dispatch.
    catalog_entry_id: UUID | None = None
    scene_id: str = Field(..., min_length=1)
    window_start_ms: int = Field(..., ge=0)
    window_end_ms: int = Field(..., gt=0)
    avg_bbox_area_pct: float = Field(..., ge=0.0, le=1.0)
    avg_confidence: float = Field(..., ge=0.0, le=1.0)
    has_narration_mention: bool = False
    has_ocr_overlap: bool = False
    co_appearing_catalog_entry_ids: list[UUID] = Field(default_factory=list)
    raw_bbox_track_s3_key: str | None = None
    tracker_version: str = Field(..., min_length=1)
    rejected_reason: str | None = None


class _CompleteRequest(BaseModel):
    """Single shape for both enum and track terminal callbacks.

    For enum jobs: ``catalog_entries`` is non-empty;
    ``appearances`` + ``render_job_id`` are unset.
    For track jobs: ``appearances`` is non-empty; ``render_job_id`` is
    set; ``catalog_entries`` is unset.
    """

    model_config = ConfigDict(extra="forbid")
    claimed_by: str = Field(..., min_length=1, max_length=200)
    cost_delta_usd: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    catalog_entries: list[_CatalogEntryPayload] = Field(default_factory=list)
    appearances: list[_AppearancePayload] = Field(default_factory=list)
    render_job_id: UUID | None = None


class _CompleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    persisted_catalog_entries: int
    persisted_appearances: int


@router.post("/{job_id}/complete", response_model=_CompleteResponse)
async def complete(
    job_id: UUID,
    body: _CompleteRequest,
    _token: Annotated[str, Depends(verify_internal_token)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _settings: Annotated[Settings, Depends(get_settings)],
) -> _CompleteResponse:
    job_repo = ProductScanJobRepository(db)
    catalog_repo = ProductCatalogRepository(db)
    appearance_repo = ProductAppearanceRepository(db)
    cost_repo = ProductScanDailyCostRepository(db)

    job = await job_repo.get_internal(job_id=job_id)
    if job is None or job.claimed_by != body.claimed_by:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="lease lost or job missing",
        )

    # Phase 4 task #1 (codex-flagged): dispatch on ``job.mode``, NOT on
    # ``catalog_entry_id IS NULL``. The pre-Phase-4 heuristic would
    # misclassify ``mode='scan_order'`` parents (which also carry
    # ``catalog_entry_id=NULL``) as enumeration jobs and 400 every
    # parent /complete.
    from app.modules.shorts_auto_product.models import (
        SCAN_MODE_ENUMERATE,
        SCAN_MODE_SCAN_ORDER,
    )

    if job.mode == SCAN_MODE_ENUMERATE and job.catalog_entry_id is None:
        kind = "enumeration"
    elif job.mode == SCAN_MODE_ENUMERATE and job.catalog_entry_id is not None:
        kind = "legacy_tracking"  # deprecated enqueue_clip flow
    elif job.mode == SCAN_MODE_SCAN_ORDER:
        kind = "scan_order"
    else:
        # ``mode='render_child'`` callers should hit /render then
        # /complete via a different flow entirely; rejecting here lets
        # us catch contract drift early.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"/complete does not accept mode={job.mode!r} via this path",
        )

    # Body-shape validation by kind.
    if kind == "enumeration" and not body.catalog_entries:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="enumeration complete must include catalog_entries",
        )
    if kind == "legacy_tracking" and not body.appearances:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tracking complete must include appearances",
        )
    if kind == "scan_order" and not body.appearances:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="scan_order complete must include appearances",
        )
    if kind == "scan_order":
        # Each appearance must carry its own catalog_entry_id (the
        # parent processed the whole catalog).
        missing = [
            i for i, app in enumerate(body.appearances)
            if app.catalog_entry_id is None
        ]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"scan_order appearances must each carry catalog_entry_id "
                    f"(missing on indices {missing[:5]}{'...' if len(missing) > 5 else ''})"
                ),
            )

    persisted_catalog = 0
    persisted_appearances = 0

    if kind == "enumeration":
        catalog_dicts: list[dict[str, object]] = []
        for entry in body.catalog_entries:
            catalog_dicts.append({
                "org_id": job.org_id,
                "video_id": job.video_id,
                "canonical_crop_s3_key": entry.canonical_crop_s3_key,
                "canonical_video_id": entry.canonical_video_id,
                "canonical_frame_idx": entry.canonical_frame_idx,
                "canonical_bbox_x": entry.canonical_bbox.x,
                "canonical_bbox_y": entry.canonical_bbox.y,
                "canonical_bbox_w": entry.canonical_bbox.w,
                "canonical_bbox_h": entry.canonical_bbox.h,
                "llm_label": entry.llm_label,
                "siglip2_embedding": entry.siglip2_embedding,
                "enumeration_confidence": entry.enumeration_confidence,
                "prominence_score": entry.prominence_score,
                "enumeration_version": entry.enumeration_version,
                "enumeration_prompt_version": entry.enumeration_prompt_version,
            })
        rows = await catalog_repo.bulk_insert(entries=catalog_dicts)
        persisted_catalog = len(rows)
        await job_repo.complete_enumeration(
            job_id=job_id,
            claimed_by=body.claimed_by,
            cost_delta_usd=body.cost_delta_usd,
        )
    else:
        # ``legacy_tracking`` derives catalog_entry_id from the job row;
        # ``scan_order`` reads it from each appearance's payload.
        legacy_catalog_entry_id = (
            job.catalog_entry_id if kind == "legacy_tracking" else None
        )
        appearance_dicts: list[dict[str, object]] = []
        for app in body.appearances:
            row_catalog_entry_id = (
                legacy_catalog_entry_id
                if kind == "legacy_tracking"
                else app.catalog_entry_id
            )
            appearance_dicts.append({
                "catalog_entry_id": row_catalog_entry_id,
                "org_id": job.org_id,
                "scene_id": app.scene_id,
                "window_start_ms": app.window_start_ms,
                "window_end_ms": app.window_end_ms,
                "avg_bbox_area_pct": app.avg_bbox_area_pct,
                "avg_confidence": app.avg_confidence,
                "has_narration_mention": app.has_narration_mention,
                "has_ocr_overlap": app.has_ocr_overlap,
                "co_appearing_catalog_entry_ids": app.co_appearing_catalog_entry_ids,
                "raw_bbox_track_s3_key": app.raw_bbox_track_s3_key,
                "tracker_version": app.tracker_version,
                "rejected_reason": app.rejected_reason,
            })
        rows = await appearance_repo.bulk_insert(appearances=appearance_dicts)
        persisted_appearances = len(rows)
        # Q4 codex pushback: scan_order parents NEVER carry render_job_id;
        # the ck_psj_parent_no_render CHECK enforces this at the DB level
        # but force NULL here too — defense in depth.
        if kind == "scan_order":
            # Phase 4 fan-out hook: transition parent to FANNED_OUT
            # (NOT DONE — parent isn't terminal until children
            # terminate) and atomically insert N children. Both
            # operations are in the same transaction as the
            # appearances insert above so a partial fan-out is
            # impossible: if the children insert fails, the entire
            # /complete returns 500 and the worker retries (lease
            # protected against double-fan-out via the claimed_by
            # check + the parent's stage transition).
            transitioned = await job_repo.transition_parent_to_fanned_out(
                job_id=job_id,
                claimed_by=body.claimed_by,
                cost_delta_usd=body.cost_delta_usd,
            )
            if transitioned is None:
                # Transition failed — parent must have been
                # cancelled / re-claimed mid-/complete. Surface as
                # 409 (lease lost) so the worker treats the message
                # as terminal and ack-deletes.
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="parent transition failed; lease lost or cancelled",
                )
            children = await job_repo.create_render_children(
                parent=transitioned,
                count=transitioned.requested_count,
            )
            logger.info(
                "product_v2_scan_order_fanned_out",
                parent_job_id=str(job_id),
                children_inserted=len(children),
                requested_count=transitioned.requested_count,
            )
        else:
            await job_repo.complete_tracking(
                job_id=job_id,
                claimed_by=body.claimed_by,
                cost_delta_usd=body.cost_delta_usd,
                render_job_id=body.render_job_id,
            )

    if body.cost_delta_usd > Decimal("0"):
        await cost_repo.add_cost(
            org_id=job.org_id, delta_usd=body.cost_delta_usd,
        )

    await db.commit()
    logger.info(
        "product_v2_job_completed",
        job_id=str(job_id),
        kind=kind,
        persisted_catalog=persisted_catalog,
        persisted_appearances=persisted_appearances,
        cost_delta_usd=str(body.cost_delta_usd),
    )
    return _CompleteResponse(
        persisted_catalog_entries=persisted_catalog,
        persisted_appearances=persisted_appearances,
    )


# ---------- fail ----------

class _FailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claimed_by: str = Field(..., min_length=1, max_length=200)
    cost_delta_usd: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    error_code: Literal[
        "llm_timeout",
        "llm_schema_mismatch",
        "no_products_detected",
        "tracker_low_confidence_global",
        "render_enqueue_failed",
        "internal_error",
        "cost_cap_exceeded",
        "video_not_found",
        "cancelled",
    ]
    error_message: str = Field(..., min_length=1, max_length=2000)


@router.post("/{job_id}/fail", status_code=status.HTTP_204_NO_CONTENT)
async def fail(
    job_id: UUID,
    body: _FailRequest,
    _token: Annotated[str, Depends(verify_internal_token)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    job_repo = ProductScanJobRepository(db)
    cost_repo = ProductScanDailyCostRepository(db)
    failed = await job_repo.fail(
        job_id=job_id,
        claimed_by=body.claimed_by,
        error_code=body.error_code,
        error_message=body.error_message,
        cost_delta_usd=body.cost_delta_usd,
    )
    if failed is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="lease lost or job missing",
        )
    if body.cost_delta_usd > Decimal("0"):
        await cost_repo.add_cost(
            org_id=failed.org_id, delta_usd=body.cost_delta_usd,
        )
    await db.commit()
    logger.warning(
        "product_v2_job_failed",
        job_id=str(job_id),
        error_code=body.error_code,
        error_message=body.error_message[:120],
    )


# ---------- catalog entry resource (Phase 3c-B) ----------

class _CatalogEntryResource(BaseModel):
    """Read-only projection of a ``ProductCatalogEntry`` for the
    track worker. Strict subset of the columns the worker needs to
    seed retrieval + SAM2 anchoring; deliberately omits embeddings,
    confidence/prominence scores, and version metadata.
    """

    model_config = ConfigDict(extra="forbid")
    catalog_entry_id: UUID
    org_id: UUID
    video_id: UUID
    canonical_crop_s3_key: str = Field(..., min_length=1)
    canonical_bbox: _BBoxXYWH
    llm_label: str = Field(..., min_length=1, max_length=200)


@router.get(
    "/catalog/{catalog_entry_id}",
    response_model=_CatalogEntryResource,
)
async def get_catalog_entry(
    catalog_entry_id: UUID,
    _token: Annotated[str, Depends(verify_internal_token)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    x_heimdex_org_id: Annotated[
        str | None, Header(alias="X-Heimdex-Org-Id"),
    ] = None,
) -> _CatalogEntryResource:
    """Pattern B fetch for the track worker's canonical-crop seed.

    Worker calls this immediately after claiming a track job to
    resolve ``(canonical_crop_s3_key, canonical_bbox, llm_label)`` —
    everything needed to download the reference crop from S3 and
    seed SigLIP2 retrieval + SAM2 anchor. Embeddings + scores are
    intentionally omitted; the worker has no use for them and
    over-projecting would expose internal scoring detail to
    every cross-service caller.

    Auth: Bearer + Pattern B path-resource scoping. Cross-tenant
    access returns 404 (NOT 403) — same response shape as a real
    not-found, no info leak about the entry's true tenant.
    Rejected entries are NOT filtered out: the track-worker has
    legitimate reasons to fetch a soft-rejected entry's seed
    metadata for diagnostic purposes; the rejection check belongs
    on the user-facing path, not the internal worker callback.
    """
    from app.lib.internal_auth import resolve_resource_with_org

    catalog_repo = ProductCatalogRepository(db)
    entry, org_id = await resolve_resource_with_org(
        resource_id=catalog_entry_id,
        x_heimdex_org_id=x_heimdex_org_id,
        lookup_fn=catalog_repo.get_by_id_resource_scoped,
        not_found_detail="catalog entry not found",
    )
    return _CatalogEntryResource(
        catalog_entry_id=entry.id,
        org_id=org_id,
        video_id=entry.video_id,
        canonical_crop_s3_key=entry.canonical_crop_s3_key,
        canonical_bbox=_BBoxXYWH(
            x=entry.canonical_bbox_x,
            y=entry.canonical_bbox_y,
            w=entry.canonical_bbox_w,
            h=entry.canonical_bbox_h,
        ),
        llm_label=entry.llm_label,
    )


# ---------- render enqueue (Phase 3c-B) ----------

class _RenderEnqueuePayloadProxy(BaseModel):
    """Mirror of :class:`shorts_render.schemas.RenderJobCreate`.

    Defined inline rather than imported from shorts_render to avoid
    cross-module circular imports during router load + to keep the
    extra='forbid' boundary explicit at the wire. Drift between
    this and ``RenderJobCreate`` would 422 here OR in the
    forwarded service call — pinned by the integration tests.
    """

    model_config = ConfigDict(extra="forbid")
    video_id: str = Field(..., min_length=1)
    title: str | None = None
    composition: dict  # Validated downstream by CompositionSpec.model_validate


class _RenderEnqueueRequest(BaseModel):
    """Worker → api request to enqueue a render for a tracking
    scan job. The body forwards the user-facing
    :class:`RenderJobCreate` payload verbatim; this endpoint adds
    the lease check + ``user_id`` derivation from the scan job row
    (workers don't carry user-facing JWTs).
    """

    model_config = ConfigDict(extra="forbid")
    claimed_by: str = Field(..., min_length=1, max_length=200)
    payload: _RenderEnqueuePayloadProxy


class _RenderEnqueueResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    render_job_id: UUID


@router.post(
    "/{job_id}/render",
    response_model=_RenderEnqueueResponse,
    status_code=status.HTTP_201_CREATED,
)
async def enqueue_render_for_scan_job(
    job_id: UUID,
    body: _RenderEnqueueRequest,
    _token: Annotated[str, Depends(verify_internal_token)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> _RenderEnqueueResponse:
    """Worker calls this immediately after building a stitch plan
    so the api owns idempotency + per-user rate limiting + budget
    accounting for the resulting render. Auth flow:

    * Bearer token → ``verify_internal_token`` (legacy global key
      OR per-service token via F1 Phase 3).
    * Lease check → ``claimed_by`` must match the scan job row.
      Stale workers whose lease already expired and was reclaimed
      cannot enqueue renders for the new owner.
    * ``org_id`` + ``requested_by_user_id`` derive from the scan
      job row; the worker never sends them. Server-of-record
      attribution stays correct even if the worker is buggy.

    Returns the new ``RenderJob.id`` so the caller can pass it to
    ``/internal/products/{job_id}/complete`` as ``render_job_id``.
    """
    from app.dependencies import get_shorts_render_service
    from app.modules.shorts_render.schemas import RenderJobCreate
    from heimdex_media_contracts.composition import CompositionSpec

    job_repo = ProductScanJobRepository(db)
    job = await job_repo.get_internal(job_id=job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="scan job not found",
        )
    if job.claimed_by != body.claimed_by:
        # 409 mirrors claim/heartbeat/complete/fail — workers know
        # to ack-delete the SQS message rather than redeliver.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="lease lost or claimed_by mismatch",
        )
    if job.catalog_entry_id is None:
        # Enumerate jobs don't render. Render enqueue from an enum
        # job is a worker bug.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="render enqueue requires a tracking job (catalog_entry_id is null)",
        )

    # Validate the composition shape before service entry — keeps
    # the 422 on the api boundary rather than letting it surface as
    # a 500 from the service-layer scene-clip validator.
    try:
        composition = CompositionSpec.model_validate(body.payload.composition)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid composition: {exc}",
        ) from exc

    payload = RenderJobCreate(
        video_id=body.payload.video_id,
        title=body.payload.title,
        composition=composition,
    )
    service = get_shorts_render_service(db=db)
    response = await service.create_render_job(
        org_id=job.org_id,
        user_id=job.requested_by_user_id,
        payload=payload,
    )
    await db.commit()
    return _RenderEnqueueResponse(render_job_id=response.id)


# ---------- list catalog entries by video (Phase 4 PR #5b) ----------

class _CatalogEntryListResponse(BaseModel):
    """Response for ``GET /internal/products/by-video/{video_id}``.

    Wraps the list of ``_CatalogEntryResource`` rows with the resolved
    ``org_id`` so the worker doesn't have to thread it from the SQS
    message body. Pattern A scoping (``X-Heimdex-Org-Id`` header
    required) — the worker has the org_id from the track-job message
    and passes it explicitly.
    """

    model_config = ConfigDict(extra="forbid")
    org_id: UUID
    video_id: UUID
    entries: list[_CatalogEntryResource]


@router.get(
    "/by-video/{video_id}",
    response_model=_CatalogEntryListResponse,
)
async def list_catalog_entries_for_video(
    video_id: UUID,
    _token: Annotated[str, Depends(verify_internal_token)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    x_heimdex_org_id: Annotated[
        str | None, Header(alias="X-Heimdex-Org-Id"),
    ] = None,
) -> _CatalogEntryListResponse:
    """List active catalog entries for a video.

    Phase 4 PR #5b — used by ``product-track-worker`` in the wizard
    parent flow (``mode='scan_order'``) to enumerate which products
    to track. The worker calls this once per parent job, then loops
    over the returned entries running the existing per-product
    track pipeline.

    Auth: Bearer + ``X-Heimdex-Org-Id`` header (Pattern A — list
    queries can't use Pattern B's resource-id resolution since the
    lookup key is the video, not a single entry).

    Returns the same ``_CatalogEntryResource`` shape per entry as
    ``GET /catalog/{catalog_entry_id}`` so the worker's track
    pipeline takes a uniform input. Embeddings + confidence /
    prominence scores are deliberately omitted — the per-catalog
    loop only needs canonical seed data + the llm_label for
    alignment.
    """
    if x_heimdex_org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Heimdex-Org-Id header is required",
        )
    try:
        org_id = UUID(x_heimdex_org_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"X-Heimdex-Org-Id is not a valid UUID: {exc}",
        ) from exc

    catalog_repo = ProductCatalogRepository(db)
    entries = await catalog_repo.list_active_by_video(
        org_id=org_id, video_id=video_id,
    )
    resources = [
        _CatalogEntryResource(
            catalog_entry_id=e.id,
            org_id=e.org_id,
            video_id=e.video_id,
            canonical_crop_s3_key=e.canonical_crop_s3_key,
            canonical_bbox=_BBoxXYWH(
                x=e.canonical_bbox_x,
                y=e.canonical_bbox_y,
                w=e.canonical_bbox_w,
                h=e.canonical_bbox_h,
            ),
            llm_label=e.llm_label,
        )
        for e in entries
    ]
    return _CatalogEntryListResponse(
        org_id=org_id, video_id=video_id, entries=resources,
    )
