"""STT-based mention extraction track for shorts-auto product mode v2.

Replaces the SAM2 visual tracking path with mention extraction over
OpenSearch ``transcript_raw`` / ``scene_caption``. The user picks a
catalog entry; this module finds the scenes that mention the product
(via BM25 over the catalog entry's ``llm_label`` + ``spoken_aliases``),
assembles them into segments, scores chunks, picks top clips, builds
a CompositionSpec, and enqueues the render.

Pipeline (orchestrated by ``service.assemble_stt_clip``):

    1. ``mention_extractor.find_mentioned_scenes(...)`` → MentionedScene[]
    2. ``segment_assembler.group_into_segments(...)`` → MentionSegment[]
    3. ``chunk_scorer.score_segment_chunks(...)``    → ScoredChunk[]
    4. ``clip_selector.select_top_chunks(...)``      → list[ScoredChunk]
    5. ``composition_builder.build_composition_spec(...)`` → CompositionSpec
    6. (caller) → ``ShortsRenderService.create_render_job(...)``

Loose-coupling: this module imports only from
``heimdex_media_contracts``, ``heimdex_media_pipelines.product_enum``
(no — pipelines are forbidden, never use), own module,
``app.lib.product_track`` (already-vendored pure math),
``app.dependencies`` (top-level DI), ``app.config``, ``app.storage.s3``,
``opensearchpy``, ``openai``. NEVER imports from ``app.modules.search.*``,
``app.modules.shorts_auto.*``, ``app.modules.shorts_render.*``, or
``app.modules.shorts.*``.

Plan: ``.claude/plans/shorts-auto-product-stt-pivot.md`` PR 2.
"""

from app.modules.shorts_auto_product.track_stt.errors import (
    MentionExtractionError,
    NoMentionsFoundError,
    SttPipelineError,
    TranscriptUnavailableError,
)
from app.modules.shorts_auto_product.track_stt.models import (
    ChunkScore,
    MentionedScene,
    MentionSegment,
    ScoredChunk,
    SttClipResult,
)

__all__ = [
    "ChunkScore",
    "MentionedScene",
    "MentionExtractionError",
    "MentionSegment",
    "NoMentionsFoundError",
    "ScoredChunk",
    "SttClipResult",
    "SttPipelineError",
    "TranscriptUnavailableError",
]
