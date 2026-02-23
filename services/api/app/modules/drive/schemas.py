from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class DriveConnectionCreate(BaseModel):
    library_id: UUID
    drive_id: str = Field(..., min_length=1, max_length=128)
    drive_name: str = Field(..., min_length=1, max_length=500)


class DriveFolderConnectionCreate(BaseModel):
    library_id: UUID
    folder_id: str = Field(..., min_length=1, max_length=256)
    folder_name: str = Field(..., min_length=1, max_length=500)
    folder_path: str = Field("", max_length=2000)


class DriveConnectionResponse(BaseModel):
    id: UUID
    org_id: UUID
    library_id: UUID
    scope_type: str
    drive_id: Optional[str] = None
    drive_name: Optional[str] = None
    folder_id: Optional[str] = None
    folder_name: Optional[str] = None
    folder_path: Optional[str] = None
    status: str
    last_sync_at: Optional[datetime] = None
    last_full_sync_at: Optional[datetime] = None
    sync_requested_at: Optional[datetime] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DriveConnectionUpdate(BaseModel):
    status: Optional[Literal["active", "paused", "disconnected"]] = None
    drive_name: Optional[str] = Field(None, min_length=1, max_length=500)


class DriveFileResponse(BaseModel):
    id: UUID
    org_id: UUID
    connection_id: UUID
    google_file_id: str
    file_name: str
    mime_type: str
    file_size_bytes: Optional[int] = None
    drive_path: Optional[str] = None
    video_id: str
    processing_status: str
    proxy_s3_key: Optional[str] = None
    proxy_duration_ms: Optional[int] = None
    proxy_size_bytes: Optional[int] = None
    scene_count: int
    retry_count: int
    last_error: Optional[str] = None
    is_deleted: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DriveFileListResponse(BaseModel):
    files: list[DriveFileResponse]
    total: int


class DriveFolderInfo(BaseModel):
    folder_path: str
    file_count: int
    indexed_count: int
    processing_count: int
    failed_count: int
    pending_count: int


class DriveFolderListResponse(BaseModel):
    folders: list[DriveFolderInfo]
    total_files: int


class SyncTriggerResponse(BaseModel):
    status: str
    sync_requested_at: datetime


class DriveStatusResponse(BaseModel):
    connected: bool
    connection_status: Optional[str] = None
    drive_name: Optional[str] = None
    last_sync_at: Optional[datetime] = None
    total_files: int = 0
    indexed: int = 0
    processing: int = 0
    pending: int = 0
    failed: int = 0
    last_indexed_at: Optional[datetime] = None


class DriveOAuthStatusResponse(BaseModel):
    connected: bool
    google_email: Optional[str] = None
    connected_at: Optional[datetime] = None


class DriveSecretCreate(BaseModel):
    sa_key_json: str = Field(..., min_length=1, description="Raw SA key JSON (will be encrypted at rest)")
    impersonate_email: str = Field(..., min_length=1, max_length=320)


class DriveSecretResponse(BaseModel):
    id: UUID
    org_id: UUID
    secret_type: str
    impersonate_email: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
