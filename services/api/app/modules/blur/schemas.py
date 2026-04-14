from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Re-use the contract-level BlurOptions so the API request body, the SQS
# message, and the worker all agree on the same pydantic model. One
# source of truth, no translation layer.
from heimdex_media_contracts.blur import (
    BlurDetectionSummary,
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
    """Public view of a blur job row."""

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
    detections_summary: dict[str, Any] | None
    error: str | None
    requested_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


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
    """

    model_config = ConfigDict(extra="forbid")

    lease_token: UUID
    status: BlurJobStatus
    blurred_s3_key: str | None = None
    manifest_s3_key: str | None = None
    detections_summary: BlurDetectionSummary | None = None
    error: str | None = None


class BlurJobHeartbeatPayload(BaseModel):
    """Worker → API: extend the lease on a long-running job."""

    model_config = ConfigDict(extra="forbid")

    lease_token: UUID
