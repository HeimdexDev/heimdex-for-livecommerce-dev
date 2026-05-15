"""Pydantic request/response schemas for video summary endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class VideoSummaryResponse(BaseModel):
    video_id: str
    summary: str
    is_edited: bool = False
    is_stale: bool = False
    model: str | None = None
    prompt_version: str | None = None
    scene_count: int = 0
    generated_at: datetime | None = None
    edited_at: datetime | None = None


class VideoSummaryEditRequest(BaseModel):
    summary: str = Field(..., min_length=1, max_length=5000)


class VideoSummaryGenerateRequest(BaseModel):
    force: bool = False
