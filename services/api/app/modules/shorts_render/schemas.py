from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from heimdex_media_contracts.composition import CompositionSpec, SubtitleSpec


class RenderJobCreate(BaseModel):
    video_id: str
    title: str | None = None
    composition: CompositionSpec


class RenderJobTitleUpdate(BaseModel):
    """Request body for ``PATCH /api/shorts/render/{job_id}``.

    Sent by the inspector panel when a user edits the title field.
    The field is a single-purpose endpoint right now (title only) —
    if other mutable fields land later, prefer adding a separate
    endpoint per field over expanding this into a generic patch.
    Keeps the schema honest about what the user can mutate.

    Empty string is allowed and stored as ``""`` so users can clear
    the title; ``None`` is treated identically. ``max_length=255``
    matches the column width on ``shorts_render_jobs``.
    """

    title: str | None = Field(default=None, max_length=255)


class RenderJobSubtitlesUpdate(BaseModel):
    """Request body for ``PATCH /api/shorts/render/{job_id}/subtitles``.

    Operator-driven subtitle edit. Two effects, applied atomically:

    1. ``input_spec.subtitles`` is replaced with the supplied list.
    2. ``refinement_source`` is set to ``'manual_edit'``, which the
       post-render Whisper hook checks via ``_check_guards`` —
       manually edited rows are NEVER overwritten by a Whisper pass.

    Per CLAUDE.md "single-field schema; do NOT widen", this is a
    SEPARATE endpoint from ``PATCH /api/shorts/render/{job_id}``
    (which only updates ``title``). New mutable fields should land
    as new endpoints, not as additional fields on either body.

    The list may be empty (operator deleted every subtitle); the
    ``manual_edit`` flag still applies in that case so a future
    Whisper pass doesn't re-fill them.
    """

    subtitles: list[SubtitleSpec] = Field(default_factory=list)


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
    thumbnail_video_id: str | None = None
    thumbnail_scene_id: str | None = None

    # Refinement chain — added by migration 056 (whisper subtitle refinement).
    # ``replaced_by_render_job_id``: forward pointer; non-NULL once a
    # refined child render exists. The wizard polls this and follows
    # the chain to swap to the refined download_url silently.
    # ``refined_from_render_job_id``: back pointer on the child to its
    # parent. Useful for debugging / audit trails. Surfaced so callers
    # can detect a refined render directly without two queries.
    # ``refinement_source``: ``'whisper'`` on refined children,
    # ``'manual_edit'`` after the operator hand-edits subtitles via
    # ``PATCH /api/shorts/render/{job_id}/subtitles``, or ``None`` for
    # canonical untouched rows. The post-render hook reads this to
    # skip refinement on hand-edited renders.
    replaced_by_render_job_id: UUID | None = None
    refined_from_render_job_id: UUID | None = None
    refinement_source: str | None = None

    # ``effective_render_job_id``: the leaf of the
    # ``replaced_by_render_job_id`` chain reachable from this row.
    # ``None`` when ``self`` is the leaf (the common case after
    # ``list_render_jobs`` filters to leaves). Populated when a
    # caller fetches an intermediate render directly — e.g., a
    # bookmarked editor URL pointing at a now-superseded render —
    # so the FE can redirect to the current canonical row instead
    # of editing stale state. ``download_url`` is ALWAYS the leaf's
    # MP4 regardless of which row was queried; this field exists
    # only to surface the leaf's id for navigation.
    effective_render_job_id: UUID | None = None

    model_config = ConfigDict(from_attributes=True)


class RenderJobListResponse(BaseModel):
    items: list[RenderJobResponse]
    total: int


class SubtitleSuggestion(BaseModel):
    text: str
    source: Literal["product_tag", "keyword_tag", "transcript"]


class SubtitleSuggestions(BaseModel):
    suggestions: list[SubtitleSuggestion]


class ShortsSummaryRequest(BaseModel):
    max_sentences: int = Field(default=2, ge=1, le=4)


class ShortsSummaryResponse(BaseModel):
    render_job_id: UUID
    summary: str
    prompt_version: str
    model: str
    cost_usd: float
    generated_at: datetime
