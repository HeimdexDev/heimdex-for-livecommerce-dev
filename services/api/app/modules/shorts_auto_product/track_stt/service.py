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
    LiveBlockTooShortError,
    NoMentionsFoundError,
    SttPipelineError,
    TranscriptUnavailableError,
)
from app.modules.shorts_auto_product.track_stt.models import (
    ScoredChunk,
    SttClipResult,
)
from app.modules.shorts_auto_product.track_stt.segmentation import (
    partition_live_blocks,
    scene_ids_in_live_blocks,
    summarize,
)
from app.modules.shorts_auto_product.track_stt.storyboard import (
    StoryboardPicker,
    StoryboardPlan,
)

logger = logging.getLogger(__name__)


# Type alias for the injected render-enqueue callable. Returns the
# render_job_id. The orchestrator constructs this — typically by
# lazy-importing ShortsRenderService and constructing a closure.
RenderEnqueuer = Callable[[CompositionSpec], Awaitable[UUID]]


# Defensive cap on the segmentation pre-fetch. Worst-case observed on
# staging is ~525 scenes per livecommerce VOD (gd_e5e15db2fca98249);
# 5000 leaves a 10× headroom for future longer recordings without
# risking an OS over-fetch.
_SEGMENTATION_SCENE_CAP = 5000


async def _fetch_scenes_for_segmentation(
    *,
    os_client: Any,
    index_alias: str,
    org_id: UUID,
    video_id: str,
) -> list[dict[str, Any]]:
    """Tiny OS query that returns just the fields the segmenter
    needs (one round trip, one source per scene).

    Lives here rather than in segmentation.py so the segmenter module
    stays pure (no I/O). Mirrors mention_extractor's pattern: I/O at
    the orchestrator boundary, pure transforms downstream.
    """
    body = {
        "size": _SEGMENTATION_SCENE_CAP,
        "query": {
            "bool": {
                "filter": [
                    {"term": {"org_id": str(org_id)}},
                    {"term": {"video_id": video_id}},
                ]
            }
        },
        "_source": [
            "scene_id",
            "start_ms",
            "end_ms",
            "speaker_transcript",
            "transcript_raw",
            "speech_segment_count",
        ],
        "sort": [{"start_ms": "asc"}],
    }
    response = await os_client.search(index=index_alias, body=body)
    return [
        hit.get("_source", {})
        for hit in response.get("hits", {}).get("hits", [])
    ]


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
    storyboard_picker: StoryboardPicker | None = None,
    storyboard_shadow_mode: bool = False,
    ocr_rerank_enabled: bool = False,
    ocr_boost: float = 0.6,
    live_only: bool = False,
    other_aliases_groups: list[list[str]] | None = None,
    mention_dominance_threshold: float = 0.0,
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
        live_only: Phase 1 segmentation gate. When ``True``, scenes
            are partitioned into live blocks (contiguous runs with
            STT speech signal) before BM25, and only scenes inside
            a live block are eligible for mention extraction. Default
            ``False`` for back-compat — caller passes
            ``settings.auto_shorts_product_v2_live_only_enabled``.
        other_aliases_groups: Wave 2.2 dominance filter. List per OTHER
            selected catalog entry of ``[llm_label, *spoken_aliases]``.
            None or empty = no-op.
        mention_dominance_threshold: 0.0 (default) = filter OFF.
            Typical staging value 0.3-0.5.

    Raises:
        :class:`NoMentionsFoundError`: BM25 found no qualifying
            scenes, OR segment assembly produced nothing above the
            ``MIN_SEGMENT_MS`` floor, OR clip selection couldn't
            assemble a window above ``_MIN_DURATION_FRACTION``.
        :class:`TranscriptUnavailableError`: BM25 hit some scenes
            but every one of them had empty ``transcript_raw`` AND
            empty ``scene_caption`` — there was nothing to score.
        :class:`LiveBlockTooShortError`: ``live_only=True`` and the
            video's combined live-block duration is shorter than the
            requested ``target_duration_ms``. Friendly-message
            failure — the wizard guides the user to a shorter clip
            length or a different source video.
        :class:`SttPipelineError`: Any other failure (OS unreachable,
            etc.). Raised by sub-modules.
    """

    # ---- 0. Live-block segmentation (Phase 1, flag-gated) ----
    #
    # When the flag is on, partition the video's scenes by STT
    # speech signal and build an allowlist of scene_ids that fall
    # inside a live block (i.e., where the host was actually
    # talking). Mention extraction filters its BM25 hits against
    # this set, so clips sourced from silent intro / outro b-roll
    # cycles are dropped before any picker sees them.
    #
    # The flag stays off for the manual shorts editor and any other
    # caller that hasn't opted in — back-compat is the default.
    scene_id_allowlist: frozenset[str] | None = None
    if live_only:
        seg_scenes = await _fetch_scenes_for_segmentation(
            os_client=os_client,
            index_alias=index_alias,
            org_id=org_id,
            video_id=os_video_id,
        )
        blocks = partition_live_blocks(seg_scenes)
        summary = summarize(seg_scenes, blocks)
        logger.info(
            "stt_pipeline_live_block_partition",
            extra={
                "org_id": str(org_id),
                "catalog_entry_id": str(catalog_entry_id),
                "video_id": os_video_id,
                "total_scenes": summary.total_scenes,
                "live_scenes": summary.live_scenes,
                "excluded_scenes": summary.excluded_scenes,
                "live_block_count": summary.live_block_count,
                "live_total_ms": summary.live_total_ms,
                "longest_live_block_ms": summary.longest_live_block_ms,
                "exclusion_pct": round(summary.exclusion_pct, 2),
            },
        )
        if summary.live_total_ms < target_duration_ms:
            # Friendly-message failure — the wizard's
            # ``friendlyParentError`` mapper turns this into the
            # Korean copy described in the error class docstring.
            raise LiveBlockTooShortError(
                f"video {os_video_id} has only {summary.live_total_ms}ms of "
                f"host commentary; requested clip is {target_duration_ms}ms"
            )
        scene_id_allowlist = scene_ids_in_live_blocks(blocks)

    # ---- 1. Mention extraction ----
    mentioned = await mention_extractor.find_mentioned_scenes(
        os_client=os_client,
        index_alias=index_alias,
        org_id=org_id,
        video_id=os_video_id,
        llm_label=llm_label,
        spoken_aliases=spoken_aliases,
        ocr_rerank_enabled=ocr_rerank_enabled,
        ocr_boost=ocr_boost,
        scene_id_allowlist=scene_id_allowlist,
    )
    # No-op when threshold<=0.0 or no other_aliases_groups.
    # Drops scenes where other selected catalogs' aliases outweigh
    # the primary catalog's in transcript + caption + ocr.
    if other_aliases_groups:
        mentioned = mention_extractor.filter_by_dominance(
            mentioned,
            primary_aliases=[llm_label, *spoken_aliases],
            other_aliases_groups=other_aliases_groups,
            threshold=mention_dominance_threshold,
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
    # Always run the legacy clip_selector so it can serve as the
    # storyboard fallback path AND the shadow-mode comparison
    # baseline. Cheap (pure function over already-scored chunks).
    selected = clip_selector.select_top_chunks(
        chunks=all_chunks, target_duration_ms=target_duration_ms,
    )

    storyboard_plan: StoryboardPlan | None = None
    if storyboard_picker is not None:
        try:
            storyboard_plan = await storyboard_picker.assemble(
                all_chunks=all_chunks,
                segments=segments,
                target_duration_ms=target_duration_ms,
                llm_label=llm_label,
                spoken_aliases=spoken_aliases,
                org_id=org_id,
            )
        except Exception as e:  # noqa: BLE001 — never let picker break render
            logger.warning(
                "stt_storyboard_picker_failed_fallback_legacy",
                extra={
                    "video_id": os_video_id,
                    "catalog_entry_id": str(catalog_entry_id),
                    "error_type": type(e).__name__,
                    "error": str(e)[:300],
                },
            )
            storyboard_plan = None

    use_storyboard_for_render = (
        storyboard_picker is not None
        and storyboard_plan is not None
        and not storyboard_plan.is_empty
        and not storyboard_shadow_mode
    )

    # Shadow-mode telemetry: emit a one-shot diff event so we can
    # see what storyboard WOULD have produced before flipping the
    # actual switch. Render still goes out using the legacy plan.
    if (
        storyboard_picker is not None
        and storyboard_shadow_mode
        and storyboard_plan is not None
    ):
        logger.info(
            "stt_storyboard_shadow_diff",
            extra={
                "video_id": os_video_id,
                "catalog_entry_id": str(catalog_entry_id),
                "legacy_chunk_count": len(selected),
                "storyboard_fragment_count": len(storyboard_plan.fragments),
                "storyboard_slots_filled": sorted(
                    s.value for s in storyboard_plan.slots_filled
                ),
                "storyboard_fallbacks_used": storyboard_plan.fallbacks_used,
            },
        )

    if not use_storyboard_for_render and not selected:
        # Neither path produced a valid plan → no clip possible.
        raise NoMentionsFoundError(
            f"no contiguous chunk window meets the duration floor for "
            f"catalog entry {catalog_entry_id} (target={target_duration_ms}ms)"
        )

    # ---- 5. Composition ----
    if use_storyboard_for_render:
        spec = composition_builder.build_composition_spec(
            storyboard=storyboard_plan,
            segments=segments,
            os_video_id=os_video_id,
            title=title,
            # legacy_os_subtitles_enabled is silently ignored on the
            # storyboard path — captions ALWAYS come from Whisper.
        )
    else:
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
