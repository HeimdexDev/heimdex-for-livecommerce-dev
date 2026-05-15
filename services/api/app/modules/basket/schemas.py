from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class BasketItemCreate(BaseModel):
    scene_id: str
    video_id: str
    video_title: str
    start_ms: int
    end_ms: int
    label: str | None = None
    thumbnail_url: str | None = None


class BasketItemResponse(BaseModel):
    id: UUID
    scene_id: str
    video_id: str
    video_title: str
    start_ms: int
    end_ms: int
    sort_order: int
    label: str | None
    thumbnail_url: str | None


class BasketCreate(BaseModel):
    name: str = Field(default="Untitled", max_length=200)


class BasketResponse(BaseModel):
    id: UUID
    name: str
    items: list[BasketItemResponse]
    item_count: int
    created_at: datetime


class BasketListResponse(BaseModel):
    baskets: list[BasketResponse]
    total: int


class ReorderRequest(BaseModel):
    item_ids: list[UUID] = Field(..., min_length=1)
