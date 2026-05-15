from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from .schemas import WorkerEventCategory, WorkerEventLevel

_MAX_MESSAGE_LEN = 4096
_MAX_METADATA_BYTES = 16 * 1024


class WorkerEventIngestRequest(BaseModel):
    service: str = Field(..., min_length=1, max_length=128)
    event_name: str = Field(..., min_length=1, max_length=256)
    category: WorkerEventCategory
    level: WorkerEventLevel
    org_id: UUID | None = None
    job_id: UUID | None = None
    video_id: UUID | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    message: str | None = Field(default=None, max_length=_MAX_MESSAGE_LEN)
    metadata: dict[str, Any] | None = None

    @field_validator("metadata")
    @classmethod
    def _bound_metadata_size(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is None:
            return v
        encoded_size = len(json.dumps(v, default=str).encode("utf-8"))
        if encoded_size > _MAX_METADATA_BYTES:
            raise ValueError(
                f"metadata exceeds {_MAX_METADATA_BYTES} bytes "
                f"(got {encoded_size} bytes JSON-serialized)"
            )
        return v


class WorkerEventIngestResponse(BaseModel):
    accepted: bool = True
