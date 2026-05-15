"""Auto-shorts subtitle distribution over a clip timeline.

The character-aware chunker (``chunk_subtitle_text`` and the merge
helper) lives in :mod:`app.lib.subtitle_chunking` so other features
(premiere export, blur, future product-track) can reuse it without
depending on auto-shorts internals. This module owns only the
auto-shorts-specific *time distribution* logic — converting chunked
text into ``(start_ms, end_ms, text)`` tuples that fan out across
the clip's window.

Same chunking heuristic as ``services/web/src/features/shorts-editor/
hooks/useEditorState.ts::chunkSubtitleText``:

* 25-char target per row (≈ 5-7 Korean eojeol; reads in 1-2s at
  livecommerce pace).
* Two-pass split — sentence boundaries first, then Korean clause
  boundaries; eojeol-greedy fallback for runaway clauses.
* Distribution timing — chunks fan out across the source clip's
  timeline window with an 800ms minimum per-chunk duration.

Pure functions. No I/O.
"""

from __future__ import annotations

import re

from app.lib.subtitle_chunking import (
    MAX_SUBTITLE_CHARS,
    chunk_subtitle_text,
    merge_chunks_to_count,
)

# Re-export so existing callers that imported these names from this
# module keep working without changing import paths. Anything new
# should import directly from :mod:`app.lib.subtitle_chunking`.
__all__ = [
    "MAX_SUBTITLE_CHARS",
    "chunk_subtitle_text",
    "distribute_subtitles_for_clip",
    "distribute_subtitles_with_speaker_timing",
    "merge_chunks_to_count",
    "parse_speaker_transcript",
    "parse_timestamp_ms",
]


# Minimum duration per displayed chunk. Auto-shorts-specific: at
# livecommerce pace, sub-800ms subtitles flicker faster than viewers
# can read them. Other features (premiere export) may want a different
# threshold; that's why this stays here, not in the lib.
_MIN_CHUNK_DURATION_MS = 800


# ``SPEAKER_00 [1:23]: text`` lines (timestamp optional). Mirror of
# the FE ``LINE_PATTERN`` in ``services/web/src/lib/speaker-transcript.ts``.
_SPEAKER_LINE_RE = re.compile(r"^(\S+?)(?:\s+\[([^\]]+)\])?\s*:\s*(.+)$")
_TIMESTAMP_RE = re.compile(r"^(\d+):(\d{1,2})$")


def parse_timestamp_ms(raw: str | None) -> int | None:
    """Parse ``"mm:ss"`` (or ``"mmm:ss"`` for hour-plus) → milliseconds.

    Returns ``None`` when the input doesn't match the format. The FE
    uses the same format on speaker_transcript turn markers, so backend
    + frontend agree on what counts as a valid timestamp.
    """
    if not raw:
        return None
    m = _TIMESTAMP_RE.match(raw.strip())
    if not m:
        return None
    minutes = int(m.group(1))
    seconds = int(m.group(2))
    return (minutes * 60 + seconds) * 1000


def parse_speaker_transcript(
    transcript: str | None,
) -> list[tuple[str, int | None]]:
    """Parse a speaker_transcript blob into ``(text, timestamp_ms)`` tuples.

    Mirrors :func:`parseSpeakerTranscript` in
    ``services/web/src/lib/speaker-transcript.ts`` so backend + FE
    agree on segmentation. Returns ``[]`` when the input is empty,
    whitespace-only, or doesn't have any parseable lines.

    Lines without a timestamp marker contribute their text with
    ``timestamp_ms=None`` — the caller falls back to uniform
    distribution for those turns.
    """
    if not transcript or not transcript.strip():
        return []
    out: list[tuple[str, int | None]] = []
    for line in transcript.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        m = _SPEAKER_LINE_RE.match(stripped)
        if not m:
            # Continuation line — append to the previous turn's text.
            if out:
                prev_text, prev_ts = out[-1]
                out[-1] = (f"{prev_text} {stripped}", prev_ts)
            continue
        timestamp = parse_timestamp_ms(m.group(2))
        text = m.group(3).strip()
        if not text:
            continue
        out.append((text, timestamp))
    return out


def distribute_subtitles_for_clip(
    *,
    transcript: str,
    timeline_start_ms: int,
    clip_duration_ms: int,
) -> list[tuple[int, int, str]]:
    """Generate subtitle (start_ms, end_ms, text) tuples for one clip.

    Args:
        transcript: The clip's underlying transcript text. Empty /
            ``None`` returns ``[]``.
        timeline_start_ms: Where on the FINAL composition timeline
            this clip starts. Subtitle ``start_ms`` and ``end_ms`` are
            timeline-relative.
        clip_duration_ms: How long the clip spans on the timeline.

    Returns:
        List of ``(start_ms, end_ms, text)`` tuples. Empty when the
        transcript yielded no chunks. Each subtitle is bounded inside
        the clip's window and is at least 800ms long; if a uniform
        distribution would produce shorter slices, we cap the chunk
        count to fit.
    """
    if not transcript or clip_duration_ms <= 0:
        return []
    chunks = chunk_subtitle_text(transcript)
    if not chunks:
        return []

    # Cap chunk count so each chunk gets at least the minimum
    # duration. A 3-second clip with 8 chunks would force 375ms each
    # — too fast to read; better to merge into 3-4 chunks of ~800ms.
    max_chunks = max(1, clip_duration_ms // _MIN_CHUNK_DURATION_MS)
    if len(chunks) > max_chunks:
        chunks = merge_chunks_to_count(chunks, max_chunks)

    chunk_duration_ms = max(
        _MIN_CHUNK_DURATION_MS,
        clip_duration_ms // len(chunks),
    )
    out: list[tuple[int, int, str]] = []
    for i, text in enumerate(chunks):
        start = timeline_start_ms + i * chunk_duration_ms
        end = min(
            start + chunk_duration_ms,
            timeline_start_ms + clip_duration_ms,
        )
        if end <= start:
            continue
        out.append((start, end, text))
    return out


def distribute_subtitles_with_speaker_timing(
    *,
    speaker_transcript: str,
    src_start_ms: int,
    src_end_ms: int,
    timeline_start_ms: int,
) -> list[tuple[int, int, str]]:
    """Time-align subtitles using ``speaker_transcript`` turn timestamps.

    Use this when scenes carry the ``"SPEAKER_00 [mm:ss]: text"``
    formatted transcript — much closer to "subtitles appear when the
    host says the words" than uniform distribution.

    Algorithm:
      1. Parse turns from speaker_transcript.
      2. Filter to turns whose timestamp lies within the clip's
         source window ``[src_start_ms, src_end_ms]``.
      3. For each kept turn, chunk its text and distribute the
         chunks across the time slot bounded by this turn's
         timestamp and the next kept turn's timestamp (or
         ``src_end_ms`` for the final turn).
      4. Convert each subtitle's source-time bounds to timeline-time
         (subtract ``src_start_ms``, add ``timeline_start_ms``).

    Returns ``[]`` when no turns fall inside the source window —
    caller should fall back to uniform distribution.
    """
    clip_duration_ms = src_end_ms - src_start_ms
    if clip_duration_ms <= 0:
        return []
    turns = parse_speaker_transcript(speaker_transcript)
    if not turns:
        return []

    # Keep only turns that have a usable timestamp inside the window.
    kept: list[tuple[int, str]] = []
    for text, ts_ms in turns:
        if ts_ms is None:
            continue
        if ts_ms < src_start_ms or ts_ms >= src_end_ms:
            continue
        kept.append((ts_ms, text))
    if not kept:
        return []

    out: list[tuple[int, int, str]] = []
    for i, (turn_ts, turn_text) in enumerate(kept):
        # Slot ends at the next kept turn's timestamp, or src_end_ms
        # for the final turn.
        next_ts = kept[i + 1][0] if i + 1 < len(kept) else src_end_ms
        slot_duration_ms = max(0, next_ts - turn_ts)
        if slot_duration_ms <= 0:
            continue
        chunks = chunk_subtitle_text(turn_text)
        if not chunks:
            continue
        max_chunks = max(1, slot_duration_ms // _MIN_CHUNK_DURATION_MS)
        if len(chunks) > max_chunks:
            chunks = merge_chunks_to_count(chunks, max_chunks)
        chunk_duration_ms = max(
            _MIN_CHUNK_DURATION_MS,
            slot_duration_ms // len(chunks),
        )
        for j, text in enumerate(chunks):
            src_chunk_start = turn_ts + j * chunk_duration_ms
            src_chunk_end = min(
                src_chunk_start + chunk_duration_ms,
                next_ts,
            )
            if src_chunk_end <= src_chunk_start:
                continue
            timeline_start = (src_chunk_start - src_start_ms) + timeline_start_ms
            timeline_end = (src_chunk_end - src_start_ms) + timeline_start_ms
            if timeline_end <= timeline_start:
                continue
            out.append((timeline_start, timeline_end, text))
    return out
