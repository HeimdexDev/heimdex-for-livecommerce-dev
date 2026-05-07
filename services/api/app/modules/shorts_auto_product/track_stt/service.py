"""Public entrypoint for the STT track. One async call from
catalog entry → render_job_id.

Loose-coupling: this orchestrator takes:
  - ``os_client`` (AsyncOpenSearch-shaped) injected by caller
  - ``openai_client`` (AsyncOpenAI-shaped) injected by caller
  - ``enqueue_render`` callable injected by caller

so the module never imports from ``app.modules.shorts_render.*`` or
``app.modules.search.*``. The orchestrator that wires this up
(``shorts_auto_product/service.py::_handle_scan_order_parent`` once
the track_mode flag is wired) does the cross-module imports — same
pattern that ``children/runner.py`` already uses for the SAM2 path.

Pipeline order (mirrors the package docstring):

    1. mention_extractor.find_mentioned_scenes
    2. segment_assembler.group_into_segments
    3. chunk_scorer.score_segment_chunks (per segment, then merged)
    4. clip_selector.select_top_chunks
    5. composition_builder.build_composition_spec
    6. enqueue_render(spec) → render_job_id

Each step emits a ``worker_events`` log line via the existing
``logging`` infra so a per-scan failure can be SQL-queried without
ssh-ing into anything (mirrors PR F's pattern from the SAM2 v5 chain).
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable
from uuid import UUID

from heimdex_media_contracts.composition.schemas import CompositionSpec

from app.modules.shorts_auto_product.track_stt import (
    chunk_scorer,
    clip_selector,
    composition_builder,
    mention_extractor,
    segment_assembler,
)
from app.modules.shorts_auto_product.track_stt.errors import (
    NoMentionsFoundError,
    SttPipelineError,
    TranscriptUnavailableError,
)
from app.modules.shorts_auto_product.track_stt.models import (
    ScoredChunk,
    SttClipResult,
)

logger = logging.getLogger(__name__)


# Type alias for the injected render-enqueue callable. Returns the
# render_job_id. The orchestrator constructs this — typically by
# lazy-importing ShortsRenderService and constructing a closure.
RenderEnqueuer = Callable[[CompositionSpec], Awaitable[UUID]]


async def assemble_stt_clip(
    *,
    org_id: UUID,
    catalog_entry_id: UUID,
    llm_label: str,
    spoken_aliases: list[str],
    os_video_id: str,
    target_duration_ms: int,
    title: str | None,
    os_client: Any,
    openai_client: Any,
    enqueue_render: RenderEnqueuer,
    index_alias: str = "heimdex_scenes",
    chunker_model: str = "gpt-4o-mini",
    legacy_os_subtitles_enabled: bool = False,
) -> SttClipResult:
    """End-to-end STT pipeline. Returns the render_job_id wrapped in
    :class:`SttClipResult`.

    Args:
        org_id: Tenant ID for the OS query filter.
        catalog_entry_id: For telemetry. The catalog row itself was
            already loaded by the caller.
        llm_label: Catalog entry's primary search term.
        spoken_aliases: Catalog entry's PR-1b-generated aliases.
        os_video_id: Drive ``video_id`` string (``"gd_..."``).
        target_duration_ms: e.g., 60_000 from the wizard.
        title: Optional title for the saved short.
        os_client: AsyncOpenSearch (real or mock).
        openai_client: AsyncOpenAI (real or mock).
        enqueue_render: Callable that accepts a ``CompositionSpec``
            and returns the produced render_job_id. The orchestrator
            wires this — usually via lazy import of
            ``ShortsRenderService.create_render_job``.
        index_alias: OpenSearch index alias. Default
            ``"heimdex_scenes"`` (the production alias).
        chunker_model: gpt-4o-mini model id. Override only for tests.

    Raises:
        :class:`NoMentionsFoundError`: BM25 found no qualifying
            scenes, OR segment assembly produced nothing above the
            ``MIN_SEGMENT_MS`` floor, OR clip selection couldn't
            assemble a window above ``_MIN_DURATION_FRACTION``.
        :class:`TranscriptUnavailableError`: BM25 hit some scenes
            but every one of them had empty ``transcript_raw`` AND
            empty ``scene_caption`` — there was nothing to score.
        :class:`SttPipelineError`: Any other failure (OS unreachable,
            etc.). Raised by sub-modules.
    """

    # ---- 1. Mention extraction ----
    mentioned = await mention_extractor.find_mentioned_scenes(
        os_client=os_client,
        index_alias=index_alias,
        org_id=org_id,
        video_id=os_video_id,
        llm_label=llm_label,
        spoken_aliases=spoken_aliases,
    )
    if not mentioned:
        logger.info(
            "stt_pipeline_no_mentions",
            extra={
                "org_id": str(org_id),
                "catalog_entry_id": str(catalog_entry_id),
                "video_id": os_video_id,
            },
        )
        raise NoMentionsFoundError(
            f"no scenes match catalog entry {catalog_entry_id} "
            f"on video {os_video_id}"
        )

    # Detect transcript_unavailable: all hits have empty transcript_raw
    # AND empty scene_caption. This shouldn't normally happen given
    # the BM25 boost ratios (we only match against those two fields),
    # but is a safety belt for malformed OS docs.
    has_any_text = any(
        (m.transcript_text or m.caption_text) for m in mentioned
    )
    if not has_any_text:
        raise TranscriptUnavailableError(
            f"video {os_video_id} has no transcript or caption text "
            f"on any matching scene"
        )

    # ---- 2. Segment assembly ----
    segments = segment_assembler.group_into_segments(mentioned)
    if not segments:
        # Mentions existed but didn't cluster into a >=20s window.
        # Indistinguishable to the user from "no mentions" — same
        # error class.
        logger.info(
            "stt_pipeline_no_qualifying_segments",
            extra={
                "video_id": os_video_id,
                "mention_count": len(mentioned),
            },
        )
        raise NoMentionsFoundError(
            f"mentions found but none clustered into a {segment_assembler.MIN_SEGMENT_MS}ms+ "
            f"segment for catalog entry {catalog_entry_id}"
        )

    # ---- 3. Chunk scoring (across all segments) ----
    all_chunks: list[ScoredChunk] = []
    for segment in segments:
        scored = await chunk_scorer.score_segment_chunks(
            segment=segment,
            openai_client=openai_client,
            model=chunker_model,
        )
        all_chunks.extend(scored)

    if not all_chunks:
        # Should be impossible given non-empty segments → at least
        # one chunk per segment. Defensive: surface as no-mentions.
        raise NoMentionsFoundError(
            f"chunk scoring produced 0 chunks despite {len(segments)} segments"
        )

    # ---- 4. Clip selection ----
    selected = clip_selector.select_top_chunks(
        chunks=all_chunks, target_duration_ms=target_duration_ms,
    )
    if not selected:
        raise NoMentionsFoundError(
            f"no contiguous chunk window meets the duration floor for "
            f"catalog entry {catalog_entry_id} (target={target_duration_ms}ms)"
        )

    # ---- 5. Composition ----
    spec = composition_builder.build_composition_spec(
        selected_chunks=selected,
        segments=segments,
        os_video_id=os_video_id,
        title=title,
        legacy_os_subtitles_enabled=legacy_os_subtitles_enabled,
    )

    # ---- 6. Render enqueue (caller-supplied) ----
    try:
        render_job_id = await enqueue_render(spec)
    except Exception as e:
        # Wrap as pipeline error so the orchestrator can map to
        # ``error_code='render_enqueue_failed'``. Callers that want
        # finer-grained handling can re-import ShortsRenderService's
        # error types directly.
        logger.exception(
            "stt_pipeline_render_enqueue_failed",
            extra={
                "video_id": os_video_id,
                "catalog_entry_id": str(catalog_entry_id),
            },
        )
        raise SttPipelineError(f"render enqueue failed: {e}") from e

    # Aggregate matched aliases for the result. Distinct via casefold.
    seen: set[str] = set()
    matched_aliases: list[str] = []
    for scene in mentioned:
        for alias in scene.matched_aliases:
            key = alias.casefold()
            if key in seen:
                continue
            seen.add(key)
            matched_aliases.append(alias)

    logger.info(
        "stt_pipeline_completed",
        extra={
            "org_id": str(org_id),
            "catalog_entry_id": str(catalog_entry_id),
            "video_id": os_video_id,
            "mentioned_scene_count": len(mentioned),
            "segment_count": len(segments),
            "selected_chunk_count": len(selected),
            "render_job_id": str(render_job_id),
            "matched_alias_count": len(matched_aliases),
        },
    )

    return SttClipResult(
        render_job_id=render_job_id,
        selected_chunks=selected,
        mentioned_scene_count=len(mentioned),
        matched_aliases=matched_aliases,
        fallback_used="none",
    )
