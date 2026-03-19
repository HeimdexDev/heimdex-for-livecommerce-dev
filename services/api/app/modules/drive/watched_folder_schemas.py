from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class WatchedFolderResponse(BaseModel):
    id: UUID
    google_folder_id: str
    folder_name: str
    folder_path: str | None = None
    parent_folder_id: str | None = None
    sync_enabled: bool
    content_types: list[str]
    file_count_cached: int
    connection_id: UUID

    model_config = {"from_attributes": True}


class WatchedFolderToggleRequest(BaseModel):
    sync_enabled: bool


class WatchedFolderContentTypesRequest(BaseModel):
    content_types: list[Literal["video", "image"]] = Field(..., min_length=1)


class ToggleFolderResponse(BaseModel):
    folder: WatchedFolderResponse
    deleted_file_count: int


class DriveInfoResponse(BaseModel):
    connection_id: UUID
    drive_id: str | None = None
    drive_name: str | None = None
    scope_type: str


class FolderTreeResponse(BaseModel):
    folders: list[WatchedFolderResponse]
    drives: list[DriveInfoResponse]


class WatchedFolderForWorkerResponse(BaseModel):
    google_folder_id: str
    content_types: list[str]


class WatchedFoldersForWorkerResponse(BaseModel):
    folders: list[WatchedFolderForWorkerResponse]
