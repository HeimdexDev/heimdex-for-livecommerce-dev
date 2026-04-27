from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from .schemas import WorkerEventCategory, WorkerEventLevel


class WorkerEventIngestRequest(BaseModel):
    service: str = Field(..., min_length=1, max_length=128)
    event_name: str = Field(..., min_length=1, max_length=256)
    category: WorkerEventCategory
    level: WorkerEventLevel
    org_id: UUID | None = None
    job_id: UUID | None = None
    video_id: UUID | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    message: str | None = None
    metadata: dict[str, Any] | None = None


class WorkerEventIngestResponse(BaseModel):
    accepted: bool = True
