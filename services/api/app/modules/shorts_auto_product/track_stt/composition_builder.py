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

**Subtitle policy (post 2026-05-07)**: this builder emits NO
subtitles. The pre-existing OS ``speaker_transcript`` field on a
scene routinely diverges from the actual audio whenever the video
gets re-split (project memory: ``project_resplit_manifest_stt_incident``),
so trusting it for caption rendering produces nonsense like
"구매하는 거 들켰어요" overlaid on agricultural-content audio.

The post-render Whisper refinement (``shorts_render/refinement_service.py``)
is the only caption source — it transcribes the actual rendered
audio, which is correct by construction. The wizard surfaces a
"자막 생성 중…" (captions generating) UX while the Whisper child
render is in flight.

Emergency rollback path: ``auto_shorts_product_v2_legacy_os_subtitles_enabled=True``
restores the historical speaker_transcript-driven subtitle
generation. Plan to delete the flag + this code path entirely
after a 2-week soak.
"""

from __future__ import annotations

import logging

from heimdex_media_contracts.composition.schemas import (
    CompositionSpec,
    SceneClipSpec,
    SubtitleSpec,
)

from app.modules.shorts_auto_product.subtitle_layout import (
    DEFAULT_CANVAS_HEIGHT,
    DEFAULT_CANVAS_WIDTH,
    build_auto_shorts_subtitle_style,
    compute_chars_per_line,
    wrap_korean_subtitle_lines,
)
from app.modules.shorts_auto_product.track_stt.models import (
    MentionSegment,
    ScoredChunk,
)
from app.modules.shorts_auto_product.track_stt.storyboard import (
    StoryboardPlan,
)

logger = logging.getLogger(__name__)


# Re-exported for backward compatibility with tests that import
# directly from this module. Prefer importing from
# ``app.modules.shorts_auto_product.subtitle_layout``.
_AUTO_SHORTS_DEFAULT_CANVAS_WIDTH = DEFAULT_CANVAS_WIDTH
_AUTO_SHORTS_DEFAULT_CANVAS_HEIGHT = DEFAULT_CANVAS_HEIGHT
_build_auto_shorts_subtitle_style = build_auto_shorts_subtitle_style
_compute_chars_per_line = compute_chars_per_line
_wrap_korean_subtitle_lines = wrap_korean_subtitle_lines


def build_composition_spec(
    *,
    selected_chunks: list[ScoredChunk] | None = None,
    storyboard: StoryboardPlan | None = None,
    segments: list[MentionSegment],
    os_video_id: str,
    title: str | None = None,
    canvas_width: int = DEFAULT_CANVAS_WIDTH,
    canvas_height: int = DEFAULT_CANVAS_HEIGHT,
    legacy_os_subtitles_enabled: bool = False,
) -> CompositionSpec:
    """Build the render-ready CompositionSpec.

    Accepts EITHER ``selected_chunks`` (legacy single-window
    selection from ``clip_selector``) OR ``storyboard`` (Tier B
    multi-fragment composition from the storyboard picker). Exactly
    one must be provided.

    Args:
        selected_chunks: Output of :func:`clip_selector.select_top_chunks`,
            already chronologically ordered. Mutually exclusive with
            ``storyboard``.
        storyboard: Output of a ``StoryboardPicker`` implementation.
            Fragments are emitted as scene_clips in storyboard order
            (HOOK → INTRO → DETAIL → CTA). Mutually exclusive with
            ``selected_chunks``.
        segments: All segments produced by the assembler — used to
            map each chunk/fragment back to its containing scene_id
            (and, in the legacy rollback path, to source caption
            text).
        os_video_id: The drive ``video_id`` string (e.g.
            ``"gd_05e7f957502e86cf"``).
        title: Optional title for the saved short. v1 wizard doesn't
            collect a title at scan time; the post-render rename
            endpoint handles user-supplied titles.
        canvas_width / canvas_height: Output dimensions used to size
            the legacy subtitle style. Defaults match
            ``OutputSpec``'s 9:16 720p portrait floor. Unused when
            ``legacy_os_subtitles_enabled`` is False (the default).
        legacy_os_subtitles_enabled: Emergency rollback toggle —
            when True, restores the historical OS-transcript-derived
            subtitle generation. False (default) emits no subtitles
            and lets Whisper post-render produce them on the actual
            audio. Only honored when ``selected_chunks`` is in use;
            the storyboard path always emits empty subtitles
            (storyboard composition is post-OS-decoupling and
            captions ALWAYS come from Whisper).

    Returns:
        ``CompositionSpec`` ready to hand to ``ShortsRenderService.create_render_job``.

    Raises:
        ValueError: Both or neither of ``selected_chunks`` /
            ``storyboard`` provided; or the input produced 0 clips
            after scene-clamping.
    """
    if (selected_chunks is None or not selected_chunks) and (
        storyboard is None or storyboard.is_empty
    ):
        raise ValueError(
            "build_composition_spec requires either non-empty "
            "selected_chunks or a non-empty storyboard"
        )
    if (
        selected_chunks is not None
        and selected_chunks
        and storyboard is not None
        and not storyboard.is_empty
    ):
        raise ValueError(
            "build_composition_spec accepts EITHER selected_chunks "
            "OR storyboard, not both"
        )

    using_storyboard = storyboard is not None and not storyboard.is_empty

    # Normalize both paths to a list of (source_start_ms,
    # source_end_ms, debug_label) ranges so the scene-clamping +
    # SceneClipSpec emission logic is shared.
    if using_storyboard:
        assert storyboard is not None  # narrow for the type checker
        ranges: list[tuple[int, int, str]] = [
            (
                f.source_start_ms,
                f.source_end_ms,
                f"storyboard:{f.role.value}",
            )
            for f in storyboard.fragments
        ]
    else:
        assert selected_chunks is not None  # narrow for the type checker
        ranges = [
            (c.start_ms, c.end_ms, "legacy_chunk")
            for c in selected_chunks
        ]

    timeline_cursor_ms = 0
    clips: list[SceneClipSpec] = []

    # Korean livecommerce scenes are 1-15s; chunks are fixed-width
    # 20s by default and storyboard fragments are clamped to slot
    # budgets (typically 8-25s). Either way, a single range routinely
    # spans multiple scenes. The render service requires each
    # ``SceneClipSpec`` to be within the underlying source scene's
    # bounds (see ``ShortsRenderService.create_render_job`` 422
    # path), so a scene-crossing range must split into N
    # ``SceneClipSpec``s — one per overlapping scene, each clamped
    # to that scene's bounds.
    sub_clip_groups: list[list[tuple[str, int, int, int]]] = []
    for range_start_ms, range_end_ms, range_label in ranges:
        sub_clips = _range_to_scene_clipped_subclips(
            range_start_ms=range_start_ms,
            range_end_ms=range_end_ms,
            segments=segments,
        )
        if not sub_clips:
            # Defensive: chunks come FROM segments, so every chunk/
            # fragment should have ≥1 overlapping scene. If somehow
            # not, skip rather than emit an invalid clip.
            logger.warning(
                "stt_composition_range_no_overlap_skipped",
                extra={
                    "range_start_ms": range_start_ms,
                    "range_end_ms": range_end_ms,
                    "range_label": range_label,
                },
            )
            continue
        timed_sub_clips: list[tuple[str, int, int, int]] = []
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
            timed_sub_clips.append(
                (scene_id, src_start_ms, src_end_ms, timeline_cursor_ms),
            )
            timeline_cursor_ms += sub_duration_ms
        sub_clip_groups.append(timed_sub_clips)

    if not clips:
        raise ValueError(
            "build_composition_spec produced 0 clips from "
            f"{len(ranges)} ranges (no scene overlap?)"
        )

    # The legacy_os_subtitles_enabled rollback ONLY makes sense
    # for the chunks path — storyboard composition is post-OS-
    # decoupling and always sources captions from Whisper. Forcing
    # the legacy path under storyboard would re-introduce the
    # exact bug the storyboard work + Whisper-only decoupling were
    # built to prevent.
    if legacy_os_subtitles_enabled and not using_storyboard:
        # Rollback path — see module docstring. Restores pre-2026-05-07
        # behavior of pulling captions from OS speaker_transcript.
        subtitles = _legacy_build_subtitles_from_os_transcripts(
            segments=segments,
            sub_clip_groups=sub_clip_groups,
            canvas_width=canvas_width,
            canvas_height=canvas_height,
        )
        log_event = "stt_composition_built_legacy_os_subs"
    else:
        # Default path — captions come from Whisper post-render. The
        # parent render goes out with no burned subtitles; the wizard
        # surfaces "자막 생성 중…" until the Whisper child lands.
        subtitles = []
        log_event = (
            "stt_composition_built_storyboard"
            if using_storyboard
            else "stt_composition_built"
        )

    spec = CompositionSpec(
        scene_clips=clips,
        subtitles=subtitles,
        title=title,
    )
    logger.info(
        log_event,
        extra={
            "video_id": os_video_id,
            "clip_count": len(clips),
            "subtitle_count": len(subtitles),
            "duration_ms": spec.total_duration_ms,
            "title": title,
            "captions_pending_whisper": not (
                legacy_os_subtitles_enabled and not using_storyboard
            ),
            "compose_mode": "storyboard" if using_storyboard else "legacy_chunks",
            "fragment_count": (
                len(storyboard.fragments) if using_storyboard else None
            ),
            "fragment_roles": (
                [f.role.value for f in storyboard.fragments]
                if using_storyboard
                else None
            ),
        },
    )
    return spec


# ---------- legacy rollback path ----------


def _legacy_build_subtitles_from_os_transcripts(
    *,
    segments: list[MentionSegment],
    sub_clip_groups: list[list[tuple[str, int, int, int]]],
    canvas_width: int,
    canvas_height: int,
) -> list[SubtitleSpec]:
    """Pre-2026-05-07 subtitle-generation path.

    Reads ``speaker_transcript`` (with ``[mm:ss]`` turn markers) and
    ``transcript_text`` (uniform-distribution fallback) from each
    scene's OS document and emits one or more ``SubtitleSpec``s per
    sub-clip. Imported lazily so the dead-code branch doesn't pay
    the import cost on the hot default path.

    Kept callable behind ``auto_shorts_product_v2_legacy_os_subtitles_enabled``
    for emergency rollback. Targeted for deletion once the new
    Whisper-only path is durably proven on prod.
    """
    from app.modules.shorts_auto_product.track_stt.subtitle_generator import (
        distribute_subtitles_for_clip,
        distribute_subtitles_with_speaker_timing,
    )

    transcript_by_scene_id: dict[str, str] = {}
    speaker_transcript_by_scene_id: dict[str, str] = {}
    for segment in segments:
        for scene in segment.scenes:
            transcript_by_scene_id[scene.scene_id] = scene.transcript_text or ""
            speaker_transcript_by_scene_id[scene.scene_id] = (
                scene.speaker_transcript or ""
            )

    subtitle_style = build_auto_shorts_subtitle_style(canvas_height=canvas_height)
    chars_per_line = compute_chars_per_line(
        canvas_width=canvas_width,
        font_size_px=subtitle_style.font_size_px,
        padding=subtitle_style.background_padding,
    )

    subtitles: list[SubtitleSpec] = []
    for group in sub_clip_groups:
        for scene_id, src_start_ms, src_end_ms, timeline_start_ms in group:
            sub_duration_ms = src_end_ms - src_start_ms
            speaker_transcript = speaker_transcript_by_scene_id.get(scene_id, "")
            speaker_timed = []
            if speaker_transcript:
                speaker_timed = distribute_subtitles_with_speaker_timing(
                    speaker_transcript=speaker_transcript,
                    src_start_ms=src_start_ms,
                    src_end_ms=src_end_ms,
                    timeline_start_ms=timeline_start_ms,
                )
            if speaker_timed:
                clip_subs = speaker_timed
            else:
                transcript = transcript_by_scene_id.get(scene_id, "")
                clip_subs = distribute_subtitles_for_clip(
                    transcript=transcript,
                    timeline_start_ms=timeline_start_ms,
                    clip_duration_ms=sub_duration_ms,
                )
            for sub_start, sub_end, text in clip_subs:
                wrapped_text = wrap_korean_subtitle_lines(
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
    return subtitles


# ---------- internals ----------


def _range_to_scene_clipped_subclips(
    *,
    range_start_ms: int,
    range_end_ms: int,
    segments: list[MentionSegment],
) -> list[tuple[str, int, int]]:
    """Split a source-time range into 1+ scene-clamped sub-clips.

    Shared between the legacy chunks path (a chunk's full range) and
    the storyboard fragment path (a fragment's clamped range). Each
    returned tuple is ``(scene_id, clamped_start_ms, clamped_end_ms)``
    where start/end are guaranteed to fall within the corresponding
    scene's actual bounds.

    Pure function. No I/O. Sub-clips are emitted in chronological
    order (ascending ``clamped_start_ms``).

    Why this exists: the render service rejects ``SceneClipSpec``s
    whose start/end fall outside the underlying scene's time range
    (``ShortsRenderService.create_render_job`` 422). Korean
    livecommerce scenes are 1-15s; chunks/fragments routinely span
    2+ scenes. Without this split, every cross-scene range 422s the
    whole render.
    """
    sub_clips: list[tuple[str, int, int]] = []
    for segment in segments:
        for scene in segment.scenes:
            overlap_start = max(range_start_ms, scene.start_ms)
            overlap_end = min(range_end_ms, scene.end_ms)
            if overlap_end <= overlap_start:
                continue
            sub_clips.append(
                (scene.scene_id, overlap_start, overlap_end),
            )

    # Multiple scenes can carry the same scene_id if the assembler
    # ever merges duplicates (currently it doesn't, but be defensive).
    # Sort by start time so the timeline cursor in the caller
    # advances monotonically per range.
    sub_clips.sort(key=lambda t: t[1])
    return sub_clips


def _chunk_to_scene_clipped_subclips(
    *,
    chunk: ScoredChunk,
    segments: list[MentionSegment],
) -> list[tuple[str, int, int]]:
    """Backwards-compatible wrapper. Prefer ``_range_to_scene_clipped_subclips``
    for new code — this exists only because some external test
    harnesses (and ``children/composition.py``) import the chunk
    helper by name.
    """
    return _range_to_scene_clipped_subclips(
        range_start_ms=chunk.start_ms,
        range_end_ms=chunk.end_ms,
        segments=segments,
    )


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
