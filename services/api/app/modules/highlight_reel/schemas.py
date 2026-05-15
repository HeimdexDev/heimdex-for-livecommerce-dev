"""Request/response schemas for highlight reel endpoints."""
from __future__ import annotations

from pydantic import BaseModel, Field


class HighlightReelPreviewRequest(BaseModel):
    target_duration_s: int = Field(default=60, ge=30, le=300)


class HighlightClipPreview(BaseModel):
    video_id: str
    video_title: str | None = None
    scene_id: str
    start_ms: int
    end_ms: int
    timeline_start_ms: int
    duration_ms: int
    run_scene_count: int


class HighlightReelPreviewResponse(BaseModel):
    person_cluster_id: str
    clips: list[HighlightClipPreview]
    total_duration_ms: int
    videos_used: int
    videos_available: int
    videos_excluded: int


class HighlightReelRenderRequest(BaseModel):
    clips: list[HighlightClipPreview]
    title: str | None = None
