"""SRT / WebVTT serializers for shorts-render subtitles.

Pure module — no I/O, no DB, no contracts coupling. Accepts the
``input_spec.subtitles`` shape stored on ``shorts_render_jobs`` (each
entry has at least ``text`` / ``start_ms`` / ``end_ms``; extra keys
like ``style`` are ignored). The output is a single ``str`` ready to
return as the body of a download response.

Why two formats:
  * SRT — universal player + NLE support (Premiere, FCPX, DaVinci,
    YouTube, VLC). Default for the wizard's "자막 다운로드" button.
  * WebVTT — needed for ``<track>`` elements in HTML5 players and
    for cleaner styling in web-native captioning. Same data shape;
    differs in millisecond separator (``,`` vs ``.``) and the WEBVTT
    header.

The serializer tolerates the staging-data quirks the runtime spec has
already learned to live with:
  * Subtitles arriving out of order — sort by ``start_ms``.
  * Zero-duration cues — skip silently rather than emit ``00:00:00,000
    --> 00:00:00,000`` rows that confuse downstream tooling.
  * Empty / whitespace-only ``text`` — skip; an editor that saved a
    blank cue produces a useless row.

Constants chosen to match the wizard's burned-in subtitle style:
millisecond precision (matches the FFmpeg drawtext timing the worker
uses) and LF line endings (``\\r\\n`` is allowed by the SRT spec but
LF works on every player I've tested and keeps the response bytes
deterministic for tests).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def subtitles_to_srt(subtitles: Iterable[Mapping[str, Any]]) -> str:
    """Serialize subtitles to SRT.

    Each cue becomes::

        N
        HH:MM:SS,mmm --> HH:MM:SS,mmm
        text

    blocks separated by a blank line. Output ends with a single
    trailing newline so the file is POSIX-clean.

    Empty or zero-duration cues are dropped — see module docstring.
    """
    cues = _normalize_cues(subtitles)
    if not cues:
        return ""

    blocks: list[str] = []
    for index, (start_ms, end_ms, text) in enumerate(cues, start=1):
        blocks.append(
            f"{index}\n"
            f"{_format_srt_timestamp(start_ms)} --> {_format_srt_timestamp(end_ms)}\n"
            f"{text}"
        )
    return "\n\n".join(blocks) + "\n"


def subtitles_to_vtt(subtitles: Iterable[Mapping[str, Any]]) -> str:
    """Serialize subtitles to WebVTT.

    Format::

        WEBVTT

        HH:MM:SS.mmm --> HH:MM:SS.mmm
        text

    The optional cue identifier line is omitted — the renderer
    doesn't need stable cue IDs for the editor download flow, and
    skipping them keeps output byte-deterministic.
    """
    cues = _normalize_cues(subtitles)
    body_blocks: list[str] = ["WEBVTT"]
    for start_ms, end_ms, text in cues:
        body_blocks.append(
            f"{_format_vtt_timestamp(start_ms)} --> {_format_vtt_timestamp(end_ms)}\n"
            f"{text}"
        )
    return "\n\n".join(body_blocks) + "\n"


# ---------- internals ----------


def _normalize_cues(
    subtitles: Iterable[Mapping[str, Any]],
) -> list[tuple[int, int, str]]:
    """Validate, filter, and sort cues into ``(start_ms, end_ms, text)``.

    Rejects entries missing required keys or with non-numeric times,
    drops zero/negative-duration cues and whitespace-only text, and
    sorts by ``start_ms`` so out-of-order PATCH bodies still produce
    a coherent file.
    """
    out: list[tuple[int, int, str]] = []
    for raw in subtitles:
        if not isinstance(raw, Mapping):
            continue
        text_raw = raw.get("text")
        start_raw = raw.get("start_ms")
        end_raw = raw.get("end_ms")
        if not isinstance(text_raw, str):
            continue
        if not isinstance(start_raw, int) or not isinstance(end_raw, int):
            continue
        text = text_raw.strip()
        if not text:
            continue
        # Clamp negatives BEFORE the duration check so a stray
        # ``start_ms=-500, end_ms=-100`` row can't slip past as a
        # nominal-positive 400ms cue and emit ``00:00:00,000 --> 00:00:00,000``.
        start_ms = max(0, start_raw)
        end_ms = max(0, end_raw)
        if end_ms <= start_ms:
            continue
        out.append((start_ms, end_ms, text))
    out.sort(key=lambda item: item[0])
    return out


def _format_srt_timestamp(ms: int) -> str:
    """``HH:MM:SS,mmm`` — comma is SRT-spec ms separator."""
    hours, minutes, seconds, millis = _split_ms(ms)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _format_vtt_timestamp(ms: int) -> str:
    """``HH:MM:SS.mmm`` — dot is WebVTT-spec ms separator."""
    hours, minutes, seconds, millis = _split_ms(ms)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def _split_ms(ms: int) -> tuple[int, int, int, int]:
    if ms < 0:
        ms = 0
    total_seconds, millis = divmod(ms, 1000)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return hours, minutes, seconds, millis
