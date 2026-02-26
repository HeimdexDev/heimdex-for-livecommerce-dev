"""Pydantic schemas for internal drive processing endpoints."""

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

ProcessingStatus = Literal[
    "downloading",
    "transcoding",
    "awaiting_transcode",
    "processing",
    "indexing",
    "indexed",
    "failed",
    "pending",
]


class ClaimProcessingRequest(BaseModel):
    limit: int = Field(default=1, ge=1, le=10)


class ClaimedProcessingFileInfo(BaseModel):
    id: UUID
    org_id: UUID
    connection_id: UUID
    google_file_id: str
    file_name: str
    video_id: str
    mime_type: str
    md5_checksum: Optional[str] = None
    file_size_bytes: Optional[int] = None
    drive_path: Optional[str] = None
    library_id: Optional[UUID] = None
    scope_type: Optional[str] = None
    drive_id: Optional[str] = None
    lease_token: str
    lease_expires_at: datetime


class ClaimProcessingResponse(BaseModel):
    files: list[ClaimedProcessingFileInfo]


class UpdateProcessingStatusRequest(BaseModel):
    status: ProcessingStatus
    lease_token: Optional[str] = None
    error: Optional[str] = Field(default=None, max_length=2000)
    proxy_s3_key: Optional[str] = None
    proxy_size_bytes: Optional[int] = None
    proxy_duration_ms: Optional[int] = None
    thumbnail_s3_prefix: Optional[str] = None
    scene_count: Optional[int] = Field(default=None, ge=0)
    audio_s3_key: Optional[str] = None
    keyframe_s3_prefix: Optional[str] = None
    original_s3_key: Optional[str] = None
    original_size_bytes: Optional[int] = None


class UpdateProcessingStatusResponse(BaseModel):
    ok: bool
