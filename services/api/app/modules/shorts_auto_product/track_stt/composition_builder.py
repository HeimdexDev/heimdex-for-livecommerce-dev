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
    SubtitleSpec,
    SubtitleStyleSpec,
)

from app.modules.shorts_auto_product.track_stt.models import (
    MentionSegment,
    ScoredChunk,
)
from app.modules.shorts_auto_product.track_stt.subtitle_generator import (
    distribute_subtitles_for_clip,
    distribute_subtitles_with_speaker_timing,
)


# White pill on black-text style — matches the operator-target
# screenshot and stays legible against any livecommerce background
# (white studio walls 흰 스튜디오 vs busy product layouts).
#
# Font size + padding are derived from the output canvas dimensions
# rather than hardcoded — keeps the look consistent if the canvas is
# bumped from 720p portrait to 1080p without an additional code
# change. See ``_build_auto_shorts_subtitle_style`` below for the
# math.

# Default canvas dimensions — match heimdex_media_contracts'
# ``OutputSpec`` defaults (406 × 720, 9:16 portrait at 720p height).
# Bumping these requires updating both this constant AND the OutputSpec
# carried in any composition that uses non-default dimensions.
_AUTO_SHORTS_DEFAULT_CANVAS_WIDTH = 406
_AUTO_SHORTS_DEFAULT_CANVAS_HEIGHT = 720

# Subtitle font size as a fraction of canvas height. 4.5% gives 32px
# at 720p and 49px at 1080p — readable on mobile, leaves ~12 Hangul
# chars of horizontal headroom per line at 9:16 portrait so the
# 어절-aware wrapper can fit most chunker-bounded cues without
# overflow. The pre-2026-05-06 hardcoded 36px overflowed at 720p
# (see staging incident: "근데 이번에 수량 좀 짜게" at 14 chars
# produced a ~450px pill on a 406-wide canvas).
_AUTO_SHORTS_FONT_SIZE_RATIO_HEIGHT = 0.045

# Floor — never render below 16px (drawtext minimum legibility).
_AUTO_SHORTS_FONT_SIZE_FLOOR_PX = 16

# Padding scales with font size (~33%) so the pill stays balanced
# at every canvas resolution.
_AUTO_SHORTS_PADDING_RATIO_FONT = 0.33
_AUTO_SHORTS_PADDING_FLOOR_PX = 8

# Max lines per cue when auto-wrapping. The upstream chunker
# (MAX_SUBTITLE_CHARS=25) keeps almost every cue inside 2 lines at
# the typical 11-13 chars/line budget — going beyond crowds the
# 9:16 frame and competes with the product staging.
_AUTO_SHORTS_MAX_SUBTITLE_LINES = 2


def _build_auto_shorts_subtitle_style(
    *, canvas_height: int,
) -> SubtitleStyleSpec:
    """Build the auto-shorts subtitle style sized to the canvas.

    Pure function. ``font_size_px`` and ``background_padding`` scale
    with ``canvas_height``; everything else (colors, weight,
    position_y) is fixed because those are design choices, not
    resolution-dependent values.
    """
    font_size_px = max(
        _AUTO_SHORTS_FONT_SIZE_FLOOR_PX,
        round(canvas_height * _AUTO_SHORTS_FONT_SIZE_RATIO_HEIGHT),
    )
    padding = max(
        _AUTO_SHORTS_PADDING_FLOOR_PX,
        round(font_size_px * _AUTO_SHORTS_PADDING_RATIO_FONT),
    )
    return SubtitleStyleSpec(
        font_color="#000000",
        background_color="#FFFFFF",
        background_opacity=0.95,
        background_padding=padding,
        font_weight=700,
        font_size_px=font_size_px,
        # Position bottom-center, slightly above the very bottom so it
        # doesn't fight with iOS / Android safe-area UI bars when the
        # short is reposted to social.
        position_y=0.82,
    )


def _compute_chars_per_line(
    *,
    canvas_width: int,
    font_size_px: int,
    padding: int,
) -> int:
    """Estimate the maximum Hangul-density chars that fit on one line.

    Hangul syllables in Pretendard Bold are ~1em wide; spaces and
    Latin chars are narrower. Using ``font_size_px`` as the per-char
    estimate gives a conservative lower bound that holds for
    all-Hangul cues. Spaces and ASCII give ~1-2 chars of headroom
    above this number — that's intentional protection against
    Pretendard's slight per-glyph variance.
    """
    available_px = max(0, canvas_width - 2 * padding)
    if font_size_px <= 0:
        return 0
    return available_px // font_size_px


def _wrap_korean_subtitle_lines(
    text: str,
    *,
    chars_per_line: int,
    max_lines: int = _AUTO_SHORTS_MAX_SUBTITLE_LINES,
) -> str:
    """Greedy 어절-aware wrap returning text with ``\\n`` at break points.

    Korean 어절 (words) are whitespace-separated; greedy left-to-right
    fills each line with as many 어절 as fit within ``chars_per_line``.
    If a single 어절 exceeds the budget, mid-syllable break — rare in
    practice (Korean words are typically ≤ 4 syllables).

    The renderer's drawtext filter interprets ``\\n`` as a line break
    and grows the background pill to enclose all lines. Multi-line
    cues stay vertically centered at ``position_y`` because drawtext
    computes the box around all lines.

    Caps at ``max_lines`` — the upstream chunker
    (MAX_SUBTITLE_CHARS=25) bounds incoming text so 2 lines suffice
    in normal operation. If text overflows even after the cap, the
    residue is appended to the last line (better to slightly
    overflow than to truncate the operator's words).
    """
    text = text.strip()
    if chars_per_line <= 0 or len(text) <= chars_per_line:
        return text

    lines: list[str] = []
    remaining = text
    while remaining and len(lines) < max_lines:
        if len(remaining) <= chars_per_line:
            lines.append(remaining)
            remaining = ""
            break
        # Last whitespace within budget+1 — the +1 lets us break AT
        # a space that lands exactly on the boundary without leaving
        # an awkward orphan word on the next line.
        window = remaining[: chars_per_line + 1]
        last_space = window.rfind(" ")
        if last_space > 0:
            lines.append(remaining[:last_space])
            remaining = remaining[last_space + 1 :].lstrip()
        else:
            # No 어절 boundary in budget — mid-syllable break. Korean
            # readers tolerate this when forced (better than dropping
            # text entirely).
            lines.append(remaining[:chars_per_line])
            remaining = remaining[chars_per_line:]

    if remaining:
        # Hit the line cap; append the residue to the last line.
        # Defensive — chunker should prevent this in practice.
        if lines:
            lines[-1] = (lines[-1] + " " + remaining).strip()
        else:
            lines.append(remaining)

    return "\n".join(lines)

logger = logging.getLogger(__name__)


def build_composition_spec(
    *,
    selected_chunks: list[ScoredChunk],
    segments: list[MentionSegment],
    os_video_id: str,
    title: str | None = None,
    canvas_width: int = _AUTO_SHORTS_DEFAULT_CANVAS_WIDTH,
    canvas_height: int = _AUTO_SHORTS_DEFAULT_CANVAS_HEIGHT,
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
        canvas_width / canvas_height: Output dimensions used to size
            the subtitle style (font + padding) and compute the
            per-line char budget for auto-wrapping. Default to
            ``OutputSpec``'s 9:16 720p portrait floor; pass through
            non-default values when the upstream wires a different
            ``OutputSpec`` so the burned-in subtitles stay
            proportionally sized.

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

    # Resolution-aware style + line budget — built once per call so
    # every emitted ``SubtitleSpec`` shares the same look and the
    # wrapper agrees with the renderer about how wide one line is.
    subtitle_style = _build_auto_shorts_subtitle_style(
        canvas_height=canvas_height,
    )
    chars_per_line = _compute_chars_per_line(
        canvas_width=canvas_width,
        font_size_px=subtitle_style.font_size_px,
        padding=subtitle_style.background_padding,
    )

    # Build per-scene lookups so we can attach the right transcript
    # AND speaker_transcript to each clamped sub-clip. The speaker
    # transcript carries [mm:ss] turn markers that let us time-align
    # subtitles to the speech; transcript_text is the uniform-
    # distribution fallback when speaker_transcript is empty.
    transcript_by_scene_id: dict[str, str] = {}
    speaker_transcript_by_scene_id: dict[str, str] = {}
    for segment in segments:
        for scene in segment.scenes:
            transcript_by_scene_id[scene.scene_id] = scene.transcript_text or ""
            speaker_transcript_by_scene_id[scene.scene_id] = (
                scene.speaker_transcript or ""
            )

    timeline_cursor_ms = 0
    clips: list[SceneClipSpec] = []
    subtitles: list[SubtitleSpec] = []

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
            # Generate subtitles for this clip. Prefer the
            # speaker_transcript path (per-turn [mm:ss] timestamps —
            # subtitles appear when the host is actually saying the
            # words) and fall back to uniform distribution over the
            # raw transcript when speaker timing isn't available.
            speaker_transcript = speaker_transcript_by_scene_id.get(scene_id, "")
            speaker_timed = []
            if speaker_transcript:
                speaker_timed = distribute_subtitles_with_speaker_timing(
                    speaker_transcript=speaker_transcript,
                    src_start_ms=src_start_ms,
                    src_end_ms=src_end_ms,
                    timeline_start_ms=timeline_cursor_ms,
                )
            if speaker_timed:
                clip_subs = speaker_timed
            else:
                transcript = transcript_by_scene_id.get(scene_id, "")
                clip_subs = distribute_subtitles_for_clip(
                    transcript=transcript,
                    timeline_start_ms=timeline_cursor_ms,
                    clip_duration_ms=sub_duration_ms,
                )
            for sub_start, sub_end, text in clip_subs:
                # Auto-wrap before emitting so a long cue arrives at
                # the renderer with explicit ``\n`` break points.
                # FFmpeg drawtext doesn't auto-wrap on width; the
                # only way to keep a 14-char Korean cue inside a
                # 406-px-wide canvas is to pre-insert the line
                # break here. See the staging 2026-05-06 incident
                # screenshot for the failure mode this prevents.
                wrapped_text = _wrap_korean_subtitle_lines(
                    text, chars_per_line=chars_per_line,
                )
                subtitles.append(
                    SubtitleSpec(
                        text=wrapped_text,
                        start_ms=sub_start,
                        end_ms=sub_end,
                        style=subtitle_style,
                    )
                )
            timeline_cursor_ms += sub_duration_ms

    if not clips:
        raise ValueError(
            "build_composition_spec produced 0 clips from "
            f"{len(selected_chunks)} chunks (no scene overlap?)"
        )

    spec = CompositionSpec(
        scene_clips=clips,
        subtitles=subtitles,
        title=title,
    )
    logger.info(
        "stt_composition_built",
        extra={
            "video_id": os_video_id,
            "clip_count": len(clips),
            "subtitle_count": len(subtitles),
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
