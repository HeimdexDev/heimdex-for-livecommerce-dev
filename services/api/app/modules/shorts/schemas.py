from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class SavedShortCreate(BaseModel):
    video_id: str
    scene_ids: list[str] = Field(..., min_length=1)
    title: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None


class SavedShortResponse(BaseModel):
    id: UUID
    video_id: str
    scene_ids: list[str]
    title: str | None
    start_ms: int | None
    end_ms: int | None
    created_at: datetime


class SavedShortsListResponse(BaseModel):
    shorts: list[SavedShortResponse]
    total: int
