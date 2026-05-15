from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

YouTubeProcessingStatus = Literal[
    "pending",
    "downloading",
    "uploading",
    "transcoding",
    "indexed",
    "enriching",
    "complete",
    "failed",
]


class RegisterChannelRequest(BaseModel):
    channel_url: str = Field(..., min_length=1, max_length=500)
    channel_name: str | None = Field(default=None, max_length=255)


class ChannelResponse(BaseModel):
    id: UUID
    channel_id: str
    channel_url: str | None
    channel_name: str
    thumbnail_url: str | None
    video_count: int
    last_synced_at: datetime | None
    sync_enabled: bool
    created_at: datetime


class ChannelListResponse(BaseModel):
    channels: list[ChannelResponse]
    total: int


class YouTubeVideoResponse(BaseModel):
    id: UUID
    org_id: UUID | None = None
    channel_id: UUID | None = None
    channel_external_id: str | None = None
    youtube_video_id: str
    video_id: str
    title: str
    duration_seconds: int | None
    publish_date: datetime | None
    processing_status: str
    has_subtitles: bool
    enrichment_status: dict[str, str | None]
    original_deleted: bool | None = None
    all_enrichment_complete: bool | None = None
    created_at: datetime


class YouTubeVideoListResponse(BaseModel):
    videos: list[YouTubeVideoResponse]
    total: int


class CreateYouTubeVideoRequest(BaseModel):
    youtube_video_id: str = Field(..., min_length=1, max_length=32)
    title: str = Field(..., min_length=1, max_length=500)
    duration_seconds: int | None = Field(default=None, ge=0)
    publish_date: datetime | None = None
    thumbnail_url: str | None = Field(default=None, max_length=500)
    description: str | None = None


class UpdateYouTubeVideoStatusRequest(BaseModel):
    processing_status: YouTubeProcessingStatus
    subtitle_language: str | None = Field(default=None, max_length=10)
    has_subtitles: bool | None = None
    enrichment_status: dict[str, str | None] | None = None
    original_deleted: bool | None = None
    scene_count: int | None = None
    keyframe_s3_prefix: str | None = None
    audio_s3_key: str | None = None


class KnownYouTubeVideoIdsResponse(BaseModel):
    video_ids: list[str]
    total: int


class SyncCompleteRequest(BaseModel):
    discovered_count: int = 0
    created_count: int = 0


class TriggerTranscodeRequest(BaseModel):
    video_id: str
    org_id: str
    youtube_video_id: str
    original_s3_key: str
    original_size_bytes: int = 0
    subtitle_s3_key: str | None = None
    metadata_s3_key: str | None = None
    has_subtitles: bool = False


class SyncTriggerResponse(BaseModel):
    status: str
