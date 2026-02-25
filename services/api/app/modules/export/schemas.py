from pydantic import BaseModel, Field


class ExportClipInput(BaseModel):
    video_id: str = Field(..., min_length=1)
    clip_name: str = Field("", max_length=200)
    start_ms: int = Field(..., ge=0)
    end_ms: int = Field(..., gt=0)


class ExportClipRequest(BaseModel):
    video_id: str = Field(..., min_length=1)
    clip_name: str = Field("", max_length=200)
    start_ms: int = Field(..., ge=0)
    end_ms: int = Field(..., gt=0)


class ExportEdlRequest(BaseModel):
    project_name: str = Field(..., min_length=1, max_length=200)
    frame_rate: float = Field(29.97, gt=0)
    clips: list[ExportClipInput] = Field(..., min_length=1)


class ExportEdlResponse(BaseModel):
    status: str = "ok"
    format: str = "edl"
    clip_count: int
    unresolved_clips: list[str]
    filename: str


class ExportPremiereRequest(BaseModel):
    project_name: str = Field(..., min_length=1, max_length=200)
    frame_rate: float = Field(29.97, gt=0)
    drive_mount_path: str = Field(
        ...,
        min_length=1,
        description="Local Google Drive mount path, e.g. /Volumes/GoogleDrive or G:\\"
    )
    clips: list[ExportClipInput] = Field(..., min_length=1)
