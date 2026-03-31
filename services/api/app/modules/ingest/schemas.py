from pydantic import BaseModel, Field

from heimdex_media_contracts.ingest import (
    IngestSceneDocument,
    IngestScenesRequest,
    SourceType,
)

__all__ = [
    "IngestSceneDocument",
    "IngestScenesRequest",
    "IngestScenesResponse",
    "EnrichSceneUpdate",
    "EnrichScenesRequest",
    "EnrichScenesResponse",
    "SourceType",
]


class IngestScenesResponse(BaseModel):
    indexed_count: int = Field(...)
    video_id: str = Field(...)
    skipped_count: int = Field(default=0)


class EnrichSceneUpdate(BaseModel):
    """Partial scene update for enrichment workers.

    Only fields explicitly set (not None) will be merged into the existing
    OpenSearch document. This prevents enrichment workers from overwriting
    each other's data.
    """

    scene_id: str = Field(...)
    transcript_raw: str | None = Field(default=None)
    speech_segment_count: int | None = Field(default=None)
    speaker_transcript: str | None = Field(default=None)
    speaker_count: int | None = Field(default=None)
    ocr_text_raw: str | None = Field(default=None)
    ocr_char_count: int | None = Field(default=None)
    scene_caption: str | None = Field(default=None)
    keyword_tags: list[str] | None = Field(default=None)
    product_tags: list[str] | None = Field(default=None)
    product_entities: list[str] | None = Field(default=None)
    ai_tags: list[str] | None = Field(default=None)
    people_cluster_ids: list[str] | None = Field(default=None)
    visual_embedding: list[float] | None = Field(default=None)


class EnrichScenesRequest(BaseModel):
    """Request to merge enrichment data into existing scenes."""

    video_id: str = Field(..., min_length=1)
    scenes: list[EnrichSceneUpdate] = Field(...)


class EnrichScenesResponse(BaseModel):
    updated_count: int = Field(...)
    video_id: str = Field(...)
    skipped_count: int = Field(default=0)
