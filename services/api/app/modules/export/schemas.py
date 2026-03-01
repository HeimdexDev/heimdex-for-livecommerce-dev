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


# --- Premiere Package Export (FCPXML 1.8) ---


class ExportPackageClipInput(BaseModel):
    """A single clip for the Premiere export package.

    Contains scene metadata needed for FCPXML generation, markers,
    and the manifest/CSV files in the ZIP package.
    """

    scene_id: str = Field(..., min_length=1)
    video_id: str = Field(..., min_length=1)
    video_title: str = Field(default="")
    start_ms: int = Field(..., ge=0)
    end_ms: int = Field(..., gt=0)
    label: str | None = Field(default=None, max_length=200)
    keyword_tags: list[str] = Field(default_factory=list)
    transcript_raw: str = Field(default="", max_length=50_000)


class ExportPremierePackageRequest(BaseModel):
    """Request to generate a Premiere Pro export package (ZIP).

    The package contains an FCPXML 1.8 timeline, manifest.json,
    README.txt, and scenes.csv. Clips reference original media
    on the user's local Google Drive mount.
    """

    sequence_name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Name for the Premiere Pro sequence",
    )
    drive_mount_path: str = Field(
        ...,
        min_length=1,
        description=(
            "Local Google Drive mount path. "
            "macOS: ~/Library/CloudStorage/GoogleDrive-email/ or /Volumes/GoogleDrive. "
            "Windows: G:\\\\ or similar."
        ),
    )
    clips: list[ExportPackageClipInput] = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Ordered list of scene clips for the timeline",
    )
    clip_gap_ms: int = Field(
        default=0,
        ge=0,
        le=5000,
        description="Gap between clips in milliseconds (0 = no gaps)",
    )
    include_markers: bool = Field(
        default=True,
        description="Add markers with scene names and tags to each clip",
    )
    include_transcript_markers: bool = Field(
        default=False,
        description="Include transcript text in clip markers",
    )


# --- Proxy Pack Export ---


class ProxyPackRequest(BaseModel):
    sequence_name: str = Field(
        ...,
        min_length=1,
        max_length=200,
    )
    clips: list[ExportPackageClipInput] = Field(
        ...,
        min_length=1,
        max_length=100,
    )
    clip_gap_ms: int = Field(default=0, ge=0, le=5000)
    include_markers: bool = Field(default=True)
    include_transcript_markers: bool = Field(default=False)


class ProxyPackInitResponse(BaseModel):
    job_id: str
    status: str = "pending"
    estimated_size_bytes: int
    proxy_count: int
    clip_count: int


class ProxyPackStatusResponse(BaseModel):
    job_id: str
    status: str
    download_url: str | None = None
    size_bytes: int | None = None
    error: str | None = None
    expires_at: str | None = None