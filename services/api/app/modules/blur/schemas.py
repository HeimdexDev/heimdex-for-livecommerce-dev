from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Re-use the contract-level BlurOptions so the API request body, the SQS
# message, and the worker all agree on the same pydantic model. One
# source of truth, no translation layer.
from heimdex_media_contracts.blur import (
    BlurCategory,
    BlurDetectionSummary,
    BlurExportFormat,
    BlurExportStatus,
    BlurJobPhase,
    BlurJobStatus,
    BlurOptions,
    BlurSourceKind,
)


class CreateBlurJobRequest(BaseModel):
    """POST /api/videos/{file_id}/blur body.

    ``options`` is optional: omitting it applies the default policy
    (faces + license plates + cards; logos OFF). ``source_kind`` is
    advisory — v1 always blurs the proxy; ``original`` is reserved.
    """

    model_config = ConfigDict(extra="forbid")

    options: BlurOptions = Field(default_factory=BlurOptions)
    source_kind: BlurSourceKind = "proxy"


class BlurJobResponse(BaseModel):
    """Public view of a blur job row.

    Raw S3 keys (``blurred_s3_key``, ``manifest_s3_key``, ``mask_s3_keys``)
    are included for internal debugging, but the frontend should always
    drive playback/detail from the *presigned URLs* below — the S3 keys
    are an implementation detail that will rotate if storage is
    reorganized. Presigned URLs are populated only when ``status=done``
    and the corresponding key is present; 1-hour TTL.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    file_id: UUID
    video_id: str
    requested_by: UUID
    status: BlurJobStatus | str  # str covers "queued"/"running" which are not in BlurJobStatus
    options: dict[str, Any]
    source_kind: BlurSourceKind | str
    blurred_s3_key: str | None
    manifest_s3_key: str | None
    mask_s3_keys: dict[str, str] | None = None
    detections_summary: dict[str, Any] | None
    error: str | None
    progress_pct: int = 0
    phase: BlurJobPhase | str | None = None
    requested_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    # Presigned URLs (populated by service layer, not from the DB row).
    blurred_playback_url: str | None = None
    manifest_url: str | None = None
    mask_urls: dict[str, str] | None = None


class BlurJobListResponse(BaseModel):
    items: list[BlurJobResponse]
    total: int


# ---------- internal callback (worker → API) ----------

class BlurJobClaim(BaseModel):
    """Worker → API: claim a queued job for processing.

    Returned by ``POST /internal/blur/{job_id}/claim``. The worker keeps
    the lease_token and presents it on every subsequent write to prove
    it still owns the job.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    org_id: UUID
    file_id: UUID
    video_id: str
    source_s3_key: str
    source_kind: BlurSourceKind | str
    options: dict[str, Any]
    lease_token: UUID
    lease_expires_at: datetime


class BlurJobCompletePayload(BaseModel):
    """Worker → API: terminal state update.

    Sent to ``POST /internal/blur/{job_id}/complete`` once the worker
    has finished or failed. Status ``cancelled`` is also valid — the
    worker may observe that the API marked the job cancelled mid-run
    and call complete() with that status and cleaned-up S3 keys set to
    None.

    ``mask_s3_keys`` is a v0.10+ addition: the worker populates it
    after uploading each per-category FFV1 mask. Optional so
    pre-v0.10 workers (without emit_masks support) still validate.
    """

    model_config = ConfigDict(extra="forbid")

    lease_token: UUID
    status: BlurJobStatus
    blurred_s3_key: str | None = None
    manifest_s3_key: str | None = None
    mask_s3_keys: dict[BlurCategory, str] | None = None
    detections_summary: BlurDetectionSummary | None = None
    error: str | None = None


class BlurJobHeartbeatPayload(BaseModel):
    """Worker → API: extend the lease on a long-running job."""

    model_config = ConfigDict(extra="forbid")

    lease_token: UUID


class BlurJobProgressPayload(BaseModel):
    """Worker → API: live progress heartbeat.

    POSTed to ``/internal/blur/{job_id}/progress`` throughout a running
    job. Doubles as a lease-refresh call — the API extends
    ``lease_expires_at`` on every progress write so workers don't have
    to maintain a separate heartbeat loop.

    Lease-token guarded for the same reason as the complete endpoint:
    a watchdog-replaced worker cannot stomp on the fresh worker's
    status.
    """

    model_config = ConfigDict(extra="forbid")

    lease_token: UUID
    progress_pct: float = Field(..., ge=0.0, le=100.0)
    phase: BlurJobPhase
    message: str | None = None


# ---------- layer export (public) ----------

class CreateBlurExportRequest(BaseModel):
    """``POST /api/blur/jobs/{job_id}/export`` body.

    The customer selects which categories to composite into the
    exported layer from the set already present on the parent job's
    ``mask_s3_keys``. Requesting a category the parent never detected
    is rejected at the service layer (409).
    """

    model_config = ConfigDict(extra="forbid")

    categories: tuple[BlurCategory, ...] = Field(..., min_length=1)
    format: BlurExportFormat = "prores_4444"


class BlurExportResponse(BaseModel):
    """Public view of a blur_exports row.

    ``download_url`` is a presigned URL to the exported ``.mov``,
    populated only when ``status=done``. 1-hour TTL — the frontend
    must not cache it past the expiry.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    blur_job_id: UUID
    file_id: UUID
    video_id: str
    requested_by: UUID
    status: BlurExportStatus | str
    categories: list[str]
    format: str
    layer_s3_key: str | None
    error: str | None
    requested_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    download_url: str | None = None


# ---------- layer export (internal worker callbacks) ----------

class BlurExportClaim(BaseModel):
    """Worker → API: claim a queued layer export.

    Returned by ``POST /internal/blur/exports/{export_id}/claim``. The
    worker uses ``source_s3_key`` (original proxy) and the category
    subset of ``mask_s3_keys`` to assemble the FFmpeg filter_complex
    pipeline that produces the ProRes 4444 alpha ``.mov``. It presents
    ``lease_token`` on the subsequent complete/fail callback.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    org_id: UUID
    file_id: UUID
    video_id: str
    blur_job_id: UUID
    source_s3_key: str
    mask_s3_keys: dict[BlurCategory, str]
    categories: tuple[BlurCategory, ...]
    format: BlurExportFormat
    lease_token: UUID
    lease_expires_at: datetime


class BlurExportCompletePayload(BaseModel):
    """Worker → API: terminal state update for a layer export."""

    model_config = ConfigDict(extra="forbid")

    lease_token: UUID
    status: BlurExportStatus
    layer_s3_key: str | None = None
    error: str | None = None
