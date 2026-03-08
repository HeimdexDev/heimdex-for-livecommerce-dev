import re
from dataclasses import dataclass
from typing import cast


@dataclass(frozen=True)
class SubtitleCue:
    start_ms: int
    end_ms: int
    text: str


_TIMESTAMP_RE = re.compile(
    r"^(?P<start>\d{2}:\d{2}:\d{2}[\.,]\d{3}|\d{2}:\d{2}[\.,]\d{3})\s+-->\s+(?P<end>\d{2}:\d{2}:\d{2}[\.,]\d{3}|\d{2}:\d{2}[\.,]\d{3})"
)


def _parse_timestamp_to_ms(raw: str) -> int:
    cleaned = raw.replace(",", ".")
    parts = cleaned.split(":")
    if len(parts) == 2:
        hours = 0
        minutes = int(parts[0])
        sec_part = parts[1]
    elif len(parts) == 3:
        hours = int(parts[0])
        minutes = int(parts[1])
        sec_part = parts[2]
    else:
        raise ValueError(f"invalid_timestamp:{raw}")

    seconds, millis = sec_part.split(".")
    return ((hours * 3600 + minutes * 60 + int(seconds)) * 1000) + int(millis)


def clean_subtitle_text(text: str) -> str:
    normalized = text.replace("♪", " ")
    normalized = re.sub(r"\[(음악|music|applause|laughter?)\]", " ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return ""

    lines: list[str] = []
    prev = ""
    for chunk in normalized.split(" "):
        if chunk == prev:
            continue
        lines.append(chunk)
        prev = chunk
    return " ".join(lines).strip()


def parse_vtt(vtt_content: str) -> list[SubtitleCue]:
    if not vtt_content.strip():
        return []

    cues: list[SubtitleCue] = []
    lines = [line.rstrip("\n") for line in vtt_content.splitlines()]
    idx = 0

    while idx < len(lines):
        line = lines[idx].strip()
        if not line or line == "WEBVTT" or line.startswith("NOTE"):
            idx += 1
            continue

        if line.isdigit() and idx + 1 < len(lines):
            idx += 1
            line = lines[idx].strip()

        match = _TIMESTAMP_RE.match(line)
        if not match:
            idx += 1
            continue

        start_ms = _parse_timestamp_to_ms(match.group("start"))
        end_ms = _parse_timestamp_to_ms(match.group("end"))
        idx += 1

        text_lines: list[str] = []
        while idx < len(lines) and lines[idx].strip():
            text_lines.append(lines[idx].strip())
            idx += 1

        text = clean_subtitle_text(" ".join(text_lines))
        if text:
            cues.append(SubtitleCue(start_ms=start_ms, end_ms=end_ms, text=text))

    return cues


def map_cues_to_scenes(cues: list[SubtitleCue], scene_boundaries_ms: list[int] | list[tuple[int, int]]) -> dict[int, str]:
    if not cues or not scene_boundaries_ms:
        return {}

    first_boundary = scene_boundaries_ms[0]
    if isinstance(first_boundary, tuple):
        ranges = cast(list[tuple[int, int]], scene_boundaries_ms)
    else:
        boundaries = scene_boundaries_ms
        ranges = []
        for i, start in enumerate(boundaries):
            end = boundaries[i + 1] if i + 1 < len(boundaries) else 10**15
            ranges.append((start, end))

    scene_texts: dict[int, list[str]] = {i: [] for i in range(len(ranges))}

    for cue in cues:
        midpoint = (cue.start_ms + cue.end_ms) // 2
        for idx, (start_ms, end_ms) in enumerate(ranges):
            if start_ms <= midpoint < end_ms:
                scene_texts[idx].append(cue.text)
                break

    result: dict[int, str] = {}
    for idx, parts in scene_texts.items():
        if parts:
            result[idx] = clean_subtitle_text(" ".join(parts))
    return result
