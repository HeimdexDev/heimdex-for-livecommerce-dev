"""
Pydantic schemas for internal drive endpoints.
Used by drive workers (caption, STT, OCR, face, visual_embed) to claim jobs and update status
via HTTP instead of direct database access.
"""
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID
from pydantic import BaseModel, Field


# ── Claim Jobs ────────────────────────────────────────────────────────

JobType = Literal["caption", "stt", "ocr", "face", "visual_embed"]


class ClaimJobsRequest(BaseModel):
    """Request body for POST /internal/drive/jobs/claim."""

    job_type: JobType
    limit: int = Field(default=1, ge=1, le=10)


class ClaimedFileInfo(BaseModel):
    """Minimal file metadata returned to workers after claiming a job."""
    id: UUID
    org_id: UUID
    video_id: str
    keyframe_s3_prefix: Optional[str] = None
    audio_s3_key: Optional[str] = None
    lease_token: str
    lease_expires_at: datetime


class ClaimJobsResponse(BaseModel):
    """Response for POST /internal/drive/jobs/claim."""

    files: list[ClaimedFileInfo]


# ── Update Job Status ─────────────────────────────────────────────────

EnrichmentStatus = Literal["done", "failed"]


class UpdateJobStatusRequest(BaseModel):
    """Request body for PATCH /internal/drive/jobs/{file_id}/status."""
    job_type: JobType
    status: EnrichmentStatus
    error: Optional[str] = Field(default=None, max_length=2000)
    lease_token: Optional[str] = None


class UpdateJobStatusResponse(BaseModel):
    """Response for PATCH /internal/drive/jobs/{file_id}/status."""

    ok: bool


# ── Get File Metadata ─────────────────────────────────────────────────

class DriveFileMetadataResponse(BaseModel):
    """Response for GET /internal/drive/files/{file_id}."""
    id: UUID
    org_id: UUID
    video_id: str
    keyframe_s3_prefix: Optional[str] = None
    audio_s3_key: Optional[str] = None
    caption_status: Optional[str] = None
    stt_status: Optional[str] = None
    ocr_status: Optional[str] = None
    enrichment_state: Optional[str] = None
    face_status: Optional[str] = None
