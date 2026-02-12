"""
Pydantic schemas for agent scene ingestion.

These DTOs define the contract between the Heimdex agent and the SaaS
ingestion endpoint. The agent sends a trimmed payload (no raw video paths,
no processing stats) and the SaaS applies normalization + embedding.

Design decisions:
- scene_id format: "{video_id}_scene_{index}" (validated via regex)
- transcript_raw sent by agent; SaaS computes transcript_norm and embedding
- source_type and capture_time are optional metadata for filtering
- No video_path or processing_time_s (agent-only fields, never sent)
"""
import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

# Scene ID must match "{video_id}_scene_{index}" pattern.
# video_id is any non-empty string; index is one or more digits.
_SCENE_ID_RE = re.compile(r"^.+_scene_\d+$")


class IngestSceneDocument(BaseModel):
    """A single scene document sent by the agent for indexing."""

    scene_id: str = Field(
        ...,
        description="Unique scene identifier. Format: {video_id}_scene_{index}",
    )
    index: int = Field(..., ge=0, description="Zero-based scene index within the video")
    start_ms: int = Field(..., ge=0, description="Scene start timestamp in milliseconds")
    end_ms: int = Field(..., ge=0, description="Scene end timestamp in milliseconds")
    keyframe_timestamp_ms: int = Field(
        default=0, ge=0, description="Representative keyframe timestamp (ms)"
    )
    transcript_raw: str = Field(
        default="",
        max_length=50_000,
        description="Raw transcript text for this scene (agent sends as-is; max 50k chars)",
    )

    @field_validator("scene_id")
    @classmethod
    def scene_id_format(cls, v: str) -> str:
        if not _SCENE_ID_RE.match(v):
            raise ValueError(
                f"scene_id must match '{{video_id}}_scene_{{index}}' pattern, got: {v!r}"
            )
        return v

    speech_segment_count: int = Field(
        default=0, ge=0, description="Number of speech segments in this scene"
    )
    people_cluster_ids: list[str] = Field(
        default_factory=list,
        description="Face cluster IDs detected in this scene",
    )
    keyword_tags: list[str] = Field(
        default_factory=list,
        description="Keyword category tags (e.g. cta, price, benefit)",
    )
    product_tags: list[str] = Field(
        default_factory=list,
        description="Product category tags (e.g. skincare, makeup)",
    )
    product_entities: list[str] = Field(
        default_factory=list,
        description="Specific product entity names found in speech",
    )
    source_type: Literal["gdrive", "removable_disk", "local"] = Field(
        default="local",
        description="Source type of the original video file",
    )
    required_drive_nickname: str | None = Field(
        default=None,
        description="Drive nickname for removable_disk sources",
    )
    capture_time: datetime | None = Field(
        default=None,
        description="Original capture/creation time of the video",
    )

    @field_validator("end_ms")
    @classmethod
    def end_after_start(cls, v: int, info) -> int:
        start = info.data.get("start_ms", 0)
        if v < start:
            raise ValueError(f"end_ms ({v}) must be >= start_ms ({start})")
        return v


class IngestScenesRequest(BaseModel):
    """Request body for POST /api/ingest/scenes."""

    video_id: str = Field(
        ...,
        min_length=1,
        description="Unique video identifier (hash or path-based ID from agent)",
    )
    video_title: str = Field(
        default="",
        max_length=500,
        description="Human-readable video title (filename without extension)",
    )
    library_id: UUID = Field(
        ...,
        description="Library UUID that this video belongs to (validated against org)",
    )
    pipeline_version: str = Field(
        default="",
        description="Scene detection pipeline version string",
    )
    model_version: str = Field(
        default="",
        description="Scene detection model version string",
    )
    total_duration_ms: int = Field(
        default=0,
        ge=0,
        description="Total video duration in milliseconds",
    )
    scenes: list[IngestSceneDocument] = Field(
        ...,
        description="Scene documents to index",
    )


class IngestScenesResponse(BaseModel):
    """Response body for POST /api/ingest/scenes."""

    indexed_count: int = Field(
        ...,
        description="Number of scenes successfully indexed",
    )
    video_id: str = Field(
        ...,
        description="Video ID that was ingested",
    )
    skipped_count: int = Field(
        default=0,
        description="Number of scenes skipped (e.g. already indexed, errors)",
    )
