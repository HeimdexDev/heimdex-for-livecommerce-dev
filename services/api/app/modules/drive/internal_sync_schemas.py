"""
Pydantic schemas for internal drive sync endpoints.

Used by the drive sync worker to claim connections, update cursors,
and upsert discovered files via HTTP instead of direct database access.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── Claim Connection ──────────────────────────────────────────────────

class ClaimSyncConnectionRequest(BaseModel):
    """Request body for POST /internal/drive/sync/claim_connection."""

    limit: int = Field(default=1, ge=1, le=10)


class ClaimedConnectionInfo(BaseModel):
    """Connection metadata returned to worker after successful claim."""

    connection_id: UUID
    org_id: UUID
    library_id: UUID
    scope_type: str
    drive_id: Optional[str] = None
    folder_id: Optional[str] = None
    folder_name: Optional[str] = None
    folder_path: Optional[str] = None
    change_token: Optional[str] = None
    last_sync_at: Optional[datetime] = None
    last_full_sync_at: Optional[datetime] = None
    lease_token: str
    lease_expires_at: datetime


class ClaimSyncConnectionResponse(BaseModel):
    """Response for POST /internal/drive/sync/claim_connection."""

    connections: list[ClaimedConnectionInfo]


# ── Checkpoint ────────────────────────────────────────────────────────

class SyncCheckpointRequest(BaseModel):
    """Request body for PATCH /internal/drive/sync/connections/{id}/checkpoint.

    lease_token is required and must match the connection's active lease.
    Set release=True (default) to clear the lease after updating cursors.
    """

    lease_token: str
    change_token: Optional[str] = None
    last_sync_at: Optional[datetime] = None
    last_full_sync_at: Optional[datetime] = None
    error_message: Optional[str] = Field(default=None, max_length=2000)
    drive_id: Optional[str] = Field(default=None, max_length=256)
    release: bool = True


class SyncCheckpointResponse(BaseModel):
    """Response for PATCH /internal/drive/sync/connections/{id}/checkpoint."""

    ok: bool


class TokenRequest(BaseModel):
    """Request body for POST /internal/drive/sync/connections/{id}/token."""

    lease_token: str | None = None


class TokenResponse(BaseModel):
    """Response for POST /internal/drive/sync/connections/{id}/token."""

    access_token: str
    token_type: str = "Bearer"
    expires_at: datetime
    scope_type: str


# ── Upsert Files ──────────────────────────────────────────────────────

class DriveDiscoveredFile(BaseModel):
    """A file discovered by the drive sync worker during Google Drive listing."""

    provider_file_id: str = Field(..., max_length=256)
    name: str = Field(..., max_length=500)
    mime_type: str = Field(..., max_length=128)
    modified_time: Optional[datetime] = None
    created_time: Optional[datetime] = None
    size: Optional[int] = Field(default=None, ge=0)
    md5_checksum: Optional[str] = Field(default=None, max_length=64)
    drive_path: Optional[str] = None
    web_view_link: Optional[str] = Field(default=None, max_length=2000)


class UpsertFilesRequest(BaseModel):
    """Request body for POST /internal/drive/sync/connections/{id}/upsert_files.

    lease_token is required and must match the connection's active lease.
    Items are deduplicated against existing files by (org_id, google_file_id).
    """

    lease_token: str
    items: list[DriveDiscoveredFile]


class UpsertFilesResponse(BaseModel):
    """Response for POST /internal/drive/sync/connections/{id}/upsert_files."""

    created_count: int
    updated_count: int
    unchanged_count: int
    enqueued_jobs: dict[str, int] = Field(default_factory=dict)
    metadata_updates: list[dict[str, str]] = Field(default_factory=list)


class DeleteFilesRequest(BaseModel):
    """Request to soft-delete files by Google file IDs."""

    lease_token: str
    google_file_ids: list[str] = Field(..., max_length=500)


class DeleteFilesResponse(BaseModel):
    """Response for soft-delete files."""

    deleted_count: int
    not_found_count: int


class MetadataUpdateItem(BaseModel):
    video_id: str
    video_title: Optional[str] = None
    source_path: Optional[str] = None


class UpdateMetadataRequest(BaseModel):
    lease_token: str
    updates: list[MetadataUpdateItem]


class UpdateMetadataResponse(BaseModel):
    updated_scene_count: int
    skipped_count: int


class ConnectionFileIdsResponse(BaseModel):
    google_file_ids: list[str] = Field(default_factory=list)
    total_count: int
