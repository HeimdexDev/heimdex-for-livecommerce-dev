from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from heimdex_media_contracts.composition import CompositionSpec


class RenderJobCreate(BaseModel):
    video_id: str
    title: str | None = None
    composition: CompositionSpec


class RenderStatusUpdate(BaseModel):
    status: Literal["rendering", "completed", "failed"]
    output_s3_key: str | None = None
    output_duration_ms: int | None = None
    output_size_bytes: int | None = None
    render_time_ms: int | None = None
    error: str | None = None


class RenderJobResponse(BaseModel):
    id: UUID
    video_id: str
    title: str | None
    status: str
    created_at: datetime
    completed_at: datetime | None
    render_time_ms: int | None
    output_duration_ms: int | None
    output_size_bytes: int | None
    error: str | None
    download_url: str | None = None

    model_config = ConfigDict(from_attributes=True)


class RenderJobListResponse(BaseModel):
    items: list[RenderJobResponse]
    total: int


class SubtitleSuggestion(BaseModel):
    text: str
    source: Literal["product_tag", "keyword_tag", "transcript"]


class SubtitleSuggestions(BaseModel):
    suggestions: list[SubtitleSuggestion]
