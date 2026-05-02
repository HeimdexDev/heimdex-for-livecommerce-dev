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
    """

    model_config = ConfigDict(extra="forbid")

    catalog_entry_id: UUID
    label: str = Field(..., min_length=1)
    canonical_crop_url: str = Field(..., min_length=1)
    enumeration_confidence: float = Field(..., ge=0.0, le=1.0)
    prominence_score: float = Field(..., ge=0.0, le=1.0)
    has_track_data: bool
    appearance_count: int | None = Field(default=None, ge=0)
    total_appearance_seconds: float | None = Field(default=None, ge=0.0)


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
