"""Pydantic DTOs for the public ``/api/shorts/auto/products/*`` API.

These are the **API boundary** types — distinct from
``heimdex_media_contracts.product`` which is the **worker boundary**.
Frontend types in ``services/web/src/lib/types/shorts-auto-product.ts``
mirror these.

Loose coupling: never import from contracts here. The mapping
between worker output (contracts) and API output (these schemas)
happens in the internal_router or service layer, not in either schema
file.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------- common ----------

DurationPresetSec = Literal[30, 60, 90]

ScanStatus = Literal[
    "never",       # no scan job has ever existed for this video
    "in_progress", # an enumeration job is queued / running
    "complete",    # at least one successful enumeration; catalog populated
    "failed",      # most recent enumeration failed terminally
]

ScanStage = Literal[
    "queued",
    "enumerating",
    "enumeration_done",
    "tracking",
    "assembling",
    "rendering",
    # Phase 4 wizard stages.
    "preview_ready",   # parent waiting on user commit (Phase 6)
    "fanned_out",      # parent waiting on N children to terminate
    "committed",       # parent terminal once all children terminate
    "done",
    "failed",
    "cancelled",
]

# Job kind discriminator (Phase 4). Mirrors the ``mode`` column on
# ``ProductScanJob`` plus the legacy "tracking" value for the deprecated
# single-product (``enqueue_clip``) flow.
#   ``enumeration``    → mode='enumerate' AND catalog_entry_id IS NULL
#   ``tracking``       → mode='enumerate' AND catalog_entry_id IS NOT NULL
#                        (legacy single-product, sunset +4wk after Phase 4 ship)
#   ``scan_order``     → mode='scan_order' (wizard parent)
#   ``render_child``   → mode='render_child' (wizard child)
JobKind = Literal["enumeration", "tracking", "scan_order", "render_child"]

ScanErrorCode = Literal[
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


# ---------- GET /products/{video_id} ----------

class CatalogProductSummary(BaseModel):
    """One product card in the gallery view.

    ``has_track_data`` flips true when the user picks this product and
    the track worker writes appearances; until then,
    ``appearance_count`` and ``total_appearance_seconds`` are ``None``
    so the UI can show a "track to see appearances" affordance.

    v0.16.0 — STT-source rows have NO canonical crop (no frame to
    crop) and NO prominence score (vision-only concept). The frontend
    falls back to a generic icon when ``canonical_crop_url`` is null;
    ``enumeration_source`` drives the badge/provenance UX.
    """

    model_config = ConfigDict(extra="forbid")

    catalog_entry_id: UUID
    label: str = Field(..., min_length=1)
    canonical_crop_url: str | None = None
    enumeration_confidence: float = Field(..., ge=0.0, le=1.0)
    prominence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    has_track_data: bool
    appearance_count: int | None = Field(default=None, ge=0)
    total_appearance_seconds: float | None = Field(default=None, ge=0.0)
    # v0.16.0 — STT-first enumeration provenance fields.
    enumeration_source: str = "vision"
    first_mention_ms: int | None = Field(default=None, ge=0)
    example_quote: str | None = None


class ProductCatalogResponse(BaseModel):
    """Response for ``GET /api/shorts/auto/products/{video_id}``."""

    model_config = ConfigDict(extra="forbid")

    video_id: UUID
    scan_status: ScanStatus
    scan_job_id: UUID | None = None        # set when scan_status="in_progress"
    enumeration_version: str | None = None  # of the populated catalog (if any)
    enumeration_prompt_version: str | None = None
    products: list[CatalogProductSummary] = Field(default_factory=list)


# ---------- POST /products/{video_id}/scan ----------

class ScanRequest(BaseModel):
    """Body for ``POST /api/shorts/auto/products/{video_id}/scan``.

    The duration preset is captured at scan time even though
    enumeration doesn't use it — it's the user's intent for the
    eventual clip and we propagate it to the tracking job so the
    user doesn't have to re-pick.
    """

    model_config = ConfigDict(extra="forbid")

    duration_preset_sec: DurationPresetSec = 60


class ScanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    # If the request hit the 60s idempotency window, ``deduped`` is
    # true and ``job_id`` is the existing job's id. Lets the UI know
    # not to double-toast.
    deduped: bool = False


# ---------- POST /products/{video_id}/{catalog_entry_id}/clip ----------

class ClipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_preset_sec: DurationPresetSec = 60


class ClipResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    deduped: bool = False
    # Render job id is None until tracking + assembly complete and the
    # render is enqueued. Frontend polls jobs/{job_id} for the
    # transition.
    render_job_id: UUID | None = None


# ---------- GET /jobs/{job_id} ----------

class JobStatusResponse(BaseModel):
    """Response for ``GET /api/shorts/auto/jobs/{job_id}``.

    Single shape for all four job kinds — the UI branches on ``kind``
    to render the right progress UI. Phase 4 added ``parent_job_id`` +
    ``shorts_index`` so children carry lineage in this flat shape too;
    the wizard's primary subscription is to the parent's aggregate
    endpoint (``GET /scan-orders/{parent_id}``) but legacy callers can
    still hit ``/jobs/{id}`` and group by parent.
    """

    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    kind: JobKind
    stage: ScanStage
    progress_pct: int = Field(..., ge=0, le=100)
    progress_label: str | None = None

    # Set on terminal states only.
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    cancelled_at: datetime | None = None
    error_code: ScanErrorCode | None = None
    error_message: str | None = None

    # Set on legacy single-product tracking jobs and on render_child
    # jobs once the render is enqueued. **Always None for scan_order
    # parents** — children own renders (Q4 codex pushback).
    render_job_id: UUID | None = None

    # v0.16.1 — the underlying ``ShortsRenderJob.status`` so the wizard
    # can distinguish "scan finished, render still in flight" from
    # "scan finished, render done". Without this the wizard's child
    # card flipped to "ready" the moment the runner enqueued the
    # render — operators clicked "스크립트 편집" and saw "렌더 결과가
    # 아직 준비되지 않았습니다" because the MP4 wasn't actually rendered
    # yet (staging incident 2026-05-06). Values mirror
    # ``ShortsRenderJob.status``: ``"queued"``, ``"rendering"``,
    # ``"completed"``, ``"failed"``. ``None`` when ``render_job_id``
    # is null (e.g., scan_order parents).
    render_status: str | None = None

    # Wizard lineage — set only on ``kind='render_child'``. Lets the
    # UI group children under their parent in the flat /jobs/{id}
    # response without an extra round-trip.
    parent_job_id: UUID | None = None
    shorts_index: int | None = None

    # Per-job running cost (running total — re-reads update across
    # heartbeats). Frontend doesn't display this in v1; it's surfaced
    # for the internal cost dashboard.
    cost_usd_estimate: Decimal


# ---------- POST /products/{video_id}/rescan ----------

class RescanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    invalidated_count: int = Field(..., ge=0)


# ---------- GET /availability (extension) ----------

class ProductV2AvailabilityFragment(BaseModel):
    """Fragment merged into the existing
    ``GET /api/shorts/auto-availability`` response. Frontend reads
    these to decide whether to render the v2 UI.
    """

    model_config = ConfigDict(extra="forbid")

    product_v2_enabled: bool
    product_v2_in_rollout: bool
    product_v2_daily_budget_remaining_pct: int = Field(..., ge=0, le=100)
    product_v2_duration_presets_sec: list[int] = Field(default_factory=list)


# ----------------------------------------------------------------------
# Phase 4 wizard — scan-order endpoints
# ----------------------------------------------------------------------

ProductDistribution = Literal["single", "multi"]
Language = Literal["ko", "en"]
ScanIntent = Literal["preview", "commit"]


class ScanOrderCreateRequest(BaseModel):
    """Body for ``POST /api/shorts/auto/scan-orders``.

    Captures every wizard input the parent job needs. Validation:
      * ``length_seconds``: 10..120 (per-shorts duration; see Q5 codex
        correction in the plan).
      * ``requested_count * length_seconds <= 1800`` (aggregate output
        cap; the daily cost ledger does NOT track render cost so this
        is the operative guard against runaway output).
      * ``time_range_*_ms``: optional; if both set, end > start AND
        ``(end - start) / count >= length_seconds * 1000`` (each short
        has at least its length in source range).
    """

    model_config = ConfigDict(extra="forbid")

    length_seconds: int = Field(..., ge=10, le=120)
    requested_count: int = Field(..., ge=1, le=50)
    time_range_start_ms: int | None = Field(default=None, ge=0)
    time_range_end_ms: int | None = Field(default=None, gt=0)
    product_distribution: ProductDistribution
    language: Language
    intent: ScanIntent = "commit"
    # Optional pre-tracking product pick (legacy single-pick — pre PR 2
    # of the multi-product wizard). Mutually exclusive with
    # ``catalog_entry_ids``; the service-layer normalizer rejects
    # bodies that set both.
    #
    # When NULL AND ``catalog_entry_ids`` is empty, legacy
    # whole-catalog round-robin behavior is preserved.
    # When set, equivalent to passing ``catalog_entry_ids=[id]``.
    catalog_entry_id: UUID | None = None

    # PR 2 (multi-product wizard): list of catalog entries the user
    # picked at the wizard's product-select step. Service-layer
    # validation enforces:
    #
    #   * ``1 <= len(catalog_entry_ids) <= requested_count`` (when set)
    #   * each entry exists, belongs to (org, video), and isn't soft-rejected
    #   * no duplicates
    #   * mutually exclusive with the legacy ``catalog_entry_id`` field
    #   * SAM2 track mode rejects ``len > 1`` (multi-select requires STT mode)
    #
    # Children get a round-robin distribution at fan-out: child[i]
    # receives ``sorted(ids)[i % len(ids)]``. With requested_count=N
    # and len=K, the first K children get one product each; remaining
    # N-K rotate through the same K. See
    # ``.claude/plans/wizard-multi-product-select.md``.
    catalog_entry_ids: list[UUID] = Field(default_factory=list)


class ScanOrderResponse(BaseModel):
    """Response for ``POST /api/shorts/auto/scan-orders``.

    Returns the parent job id; the wizard then subscribes to
    ``GET /scan-orders/{parent_job_id}`` for aggregate status.
    """

    model_config = ConfigDict(extra="forbid")

    parent_job_id: UUID
    deduped: bool = False


class ScanOrderStatusResponse(BaseModel):
    """Response for ``GET /api/shorts/auto/scan-orders/{parent_job_id}``.

    The wizard's primary subscription. One round-trip yields the
    full picture (parent + all children + their progress) — frontend
    does not poll N+1 endpoints.
    """

    model_config = ConfigDict(extra="forbid")

    parent: JobStatusResponse
    children: list[JobStatusResponse] = Field(default_factory=list)
    # Wizard-level rollup so the UI doesn't have to compute it. None
    # while the parent is still in non-fanned-out states.
    children_complete: int = Field(..., ge=0)
    children_failed: int = Field(..., ge=0)
    children_total: int = Field(..., ge=0)


class ScanOrderCommitRequest(BaseModel):
    """Body for ``POST /api/shorts/auto/scan-orders/{parent_job_id}/commit``.

    Phase 6 endpoint — currently returns 501. Body shape locked now
    so the frontend wizard can be built against a stable contract.
    Optional ``selected_window_ids`` lets the user drop preview
    windows before SAM2 + render-enqueue runs in commit mode.
    """

    model_config = ConfigDict(extra="forbid")

    selected_window_ids: list[UUID] | None = None
