"""ScoredChunk[] → CompositionSpec adapter.

Mirrors ``children/composition.py::build_composition_spec_from_stitch_plan``
but takes our STT pipeline's ``ScoredChunk[]`` instead of SAM2's
``StitchPlan``. The output shape is identical — the renderer doesn't
care which path produced the spec.

Pure function. No I/O.

Caveats inherited from the existing wizard adapter:

* ``scene_id`` per-clip is approximate — track_stt scoring works on
  fixed-width chunks, not scene boundaries, so we attach the
  ``scene_id`` of the underlying ``MentionedScene`` whose interval
  most overlaps the chunk window. The renderer doesn't actually
  branch on ``scene_id`` (it cuts on ``start_ms``/``end_ms``); the
  field is preserved for downstream search-result attribution.
* ``video_id`` is the OS string id (``gd_…``), not the
  ``drive_files.id`` UUID. ``SceneClipSpec.video_id`` accepts the
  same shape ``RenderJobCreate`` already takes.
* All clips share one ``video_id`` since v1 product mode is single-video.
"""

from __future__ import annotations

import logging

from heimdex_media_contracts.composition.schemas import (
    CompositionSpec,
    SceneClipSpec,
)

from app.modules.shorts_auto_product.track_stt.models import (
    MentionSegment,
    ScoredChunk,
)

logger = logging.getLogger(__name__)


def build_composition_spec(
    *,
    selected_chunks: list[ScoredChunk],
    segments: list[MentionSegment],
    os_video_id: str,
    title: str | None = None,
) -> CompositionSpec:
    """Build the render-ready CompositionSpec.

    Args:
        selected_chunks: Output of :func:`clip_selector.select_top_chunks`,
            already chronologically ordered.
        segments: All segments produced by the assembler — used to
            map each chunk back to its containing scene_id.
        os_video_id: The drive ``video_id`` string (e.g.
            ``"gd_05e7f957502e86cf"``).
        title: Optional title for the saved short. v1 wizard doesn't
            collect a title at scan time; the post-render rename
            endpoint handles user-supplied titles.

    Returns:
        ``CompositionSpec`` ready to hand to ``ShortsRenderService.create_render_job``.

    Raises:
        ValueError: ``selected_chunks`` is empty. Caller must surface
            ``NoMentionsFoundError`` upstream rather than build an
            invalid spec — :class:`CompositionSpec.scene_clips` has
            ``min_length=1``.
    """
    if not selected_chunks:
        raise ValueError(
            "build_composition_spec requires at least one selected "
            "chunk; caller must surface no-mentions earlier"
        )

    timeline_cursor_ms = 0
    clips: list[SceneClipSpec] = []

    # Korean livecommerce scenes are 1-15s; chunks are fixed-width 20s
    # by default. A chunk routinely spans multiple scenes. The render
    # service requires each ``SceneClipSpec`` to be within the
    # underlying source scene's bounds (see
    # ``ShortsRenderService.create_render_job`` 422 path), so a
    # scene-crossing chunk must split into N ``SceneClipSpec``s — one
    # per overlapping scene, each clamped to that scene's bounds.
    for chunk in selected_chunks:
        sub_clips = _chunk_to_scene_clipped_subclips(
            chunk=chunk, segments=segments,
        )
        if not sub_clips:
            # Defensive: chunks come FROM segments, so every chunk
            # should have ≥1 overlapping scene. If somehow not,
            # skip rather than emit an invalid clip.
            logger.warning(
                "stt_composition_chunk_no_overlap_skipped",
                extra={
                    "chunk_start_ms": chunk.start_ms,
                    "chunk_end_ms": chunk.end_ms,
                },
            )
            continue
        for scene_id, src_start_ms, src_end_ms in sub_clips:
            sub_duration_ms = src_end_ms - src_start_ms
            if sub_duration_ms <= 0:
                continue
            clips.append(
                SceneClipSpec(
                    scene_id=scene_id,
                    video_id=os_video_id,
                    source_type="gdrive",
                    start_ms=src_start_ms,
                    end_ms=src_end_ms,
                    timeline_start_ms=timeline_cursor_ms,
                    volume=1.0,
                )
            )
            timeline_cursor_ms += sub_duration_ms

    if not clips:
        raise ValueError(
            "build_composition_spec produced 0 clips from "
            f"{len(selected_chunks)} chunks (no scene overlap?)"
        )

    spec = CompositionSpec(scene_clips=clips, title=title)
    logger.info(
        "stt_composition_built",
        extra={
            "video_id": os_video_id,
            "clip_count": len(clips),
            "duration_ms": spec.total_duration_ms,
            "title": title,
        },
    )
    return spec


# ---------- internals ----------


def _chunk_to_scene_clipped_subclips(
    *,
    chunk: ScoredChunk,
    segments: list[MentionSegment],
) -> list[tuple[str, int, int]]:
    """Split a chunk into 1+ scene-clamped sub-clips.

    Each returned tuple is ``(scene_id, clamped_start_ms, clamped_end_ms)``
    where the start/end are guaranteed to be within the corresponding
    scene's actual bounds. Sub-clips are emitted in chronological
    order (ascending ``clamped_start_ms``).

    Pure function. No I/O. Trivially testable.

    Why this exists: the render service rejects ``SceneClipSpec``s
    whose start/end fall outside the underlying scene's time range
    (``ShortsRenderService.create_render_job`` 422). My chunks are
    fixed-width 20s windows that frequently span 2+ Korean
    livecommerce scenes (1-15s each). Without this split, every
    chunk that crosses a scene boundary 422s the whole render.
    """
    chunk_start_ms = chunk.start_ms
    chunk_end_ms = chunk.end_ms
    sub_clips: list[tuple[str, int, int]] = []

    for segment in segments:
        for scene in segment.scenes:
            overlap_start = max(chunk_start_ms, scene.start_ms)
            overlap_end = min(chunk_end_ms, scene.end_ms)
            if overlap_end <= overlap_start:
                continue
            sub_clips.append(
                (scene.scene_id, overlap_start, overlap_end),
            )

    # Multiple scenes can carry the same scene_id if the assembler
    # ever merges duplicates (currently it doesn't, but be defensive).
    # Sort by start time so the timeline cursor in the caller
    # advances monotonically per chunk.
    sub_clips.sort(key=lambda t: t[1])
    return sub_clips


def _attach_scene_id(
    *,
    chunk: ScoredChunk,
    segments: list[MentionSegment],
) -> str:
    """Find the scene_id whose [start_ms, end_ms] interval overlaps
    the chunk most. Falls back to the first segment's first scene
    if no overlap is found (defensive — shouldn't happen because
    chunks are built FROM segments).
    """
    best_scene_id = ""
    best_overlap = -1

    for segment in segments:
        for scene in segment.scenes:
            overlap_start = max(chunk.start_ms, scene.start_ms)
            overlap_end = min(chunk.end_ms, scene.end_ms)
            overlap = overlap_end - overlap_start
            if overlap > best_overlap:
                best_overlap = overlap
                best_scene_id = scene.scene_id

    if not best_scene_id and segments and segments[0].scenes:
        # Defensive fallback — should never trip given chunks come
        # FROM segments, but keep CompositionSpec valid even if a
        # future change inverts that invariant.
        best_scene_id = segments[0].scenes[0].scene_id

    return best_scene_id
