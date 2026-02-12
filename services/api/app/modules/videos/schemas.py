"""
Pydantic schemas for the video visibility endpoints.

All data is derived from OpenSearch scene aggregations — no Postgres table.
"""
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Video list
# ---------------------------------------------------------------------------

class VideoSummary(BaseModel):
    """A single video derived from scene aggregations."""
    video_id: str
    video_title: str | None = None
    library_id: str | None = None
    library_name: str | None = None
    source_type: Literal["gdrive", "removable_disk", "local"] | None = None
    scene_count: int = 0
    first_scene_start_ms: int = 0
    last_scene_end_ms: int = 0
    earliest_ingest_time: str | None = None
    latest_ingest_time: str | None = None
    first_scene_keyframe_ms: int = 0
    keyword_tags: list[str] = Field(default_factory=list)
    product_tags: list[str] = Field(default_factory=list)
    people_count: int = 0
    required_drive_nickname: str | None = None


class VideoFacetItem(BaseModel):
    id: str
    name: str | None = None
    count: int


class VideoFacets(BaseModel):
    libraries: list[VideoFacetItem] = Field(default_factory=list)
    source_types: list[VideoFacetItem] = Field(default_factory=list)


class VideoListResponse(BaseModel):
    videos: list[VideoSummary]
    total: int
    next_cursor: str | None = None
    facets: VideoFacets


# ---------------------------------------------------------------------------
# Video scenes
# ---------------------------------------------------------------------------

class VideoScene(BaseModel):
    """A single scene within a video detail view."""
    scene_id: str
    start_ms: int
    end_ms: int
    transcript_raw: str = ""
    transcript_char_count: int = 0
    keyword_tags: list[str] = Field(default_factory=list)
    product_tags: list[str] = Field(default_factory=list)
    product_entities: list[str] = Field(default_factory=list)
    speech_segment_count: int = 0
    people_cluster_ids: list[str] = Field(default_factory=list)
    ingest_time: str | None = None
    keyframe_timestamp_ms: int = 0


class VideoScenesResponse(BaseModel):
    video_id: str
    scenes: list[VideoScene]
    total: int


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

class VideoStats(BaseModel):
    total_videos: int = 0
    total_scenes: int = 0
    total_libraries: int = 0
    source_breakdown: dict[str, int] = Field(default_factory=dict)
    latest_ingest_time: str | None = None
    scenes_last_24h: int = 0
    scenes_last_7d: int = 0
