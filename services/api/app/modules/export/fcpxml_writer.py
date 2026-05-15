from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from hashlib import md5
from urllib.parse import quote
import xml.etree.ElementTree as ET


STANDARD_FPS: tuple[float, ...] = (23.976, 24.0, 25.0, 29.97, 30.0, 50.0, 59.94, 60.0)

_FPS_RATIONAL_MAP: dict[float, tuple[int, int]] = {
    23.976: (1001, 24000),
    24.0: (100, 2400),
    25.0: (100, 2500),
    29.97: (1001, 30000),
    30.0: (100, 3000),
    50.0: (100, 5000),
    59.94: (1001, 60000),
    60.0: (100, 6000),
}


@dataclass(frozen=True)
class ClipMarker:
    start_ms: int
    end_ms: int | None = None
    note: str = ""
    value: str = "standard"


@dataclass(frozen=True)
class TranscriptMarker:
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class FCPXMLClip:
    clip_name: str
    file_path: str
    start_ms: int
    end_ms: int
    fps: float | int | str | None = None
    width: int = 1920
    height: int = 1080
    has_video: bool = True
    has_audio: bool = True
    audio_sources: int = 1
    audio_channels: int = 2
    source_start_ms: int = 0
    markers: tuple[ClipMarker, ...] = field(default_factory=tuple)
    transcript_markers: tuple[TranscriptMarker, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class FCPXMLWriteOptions:
    event_name: str = "Heimdex Export"
    gap_ms: int = 0
    include_markers: bool = True
    include_transcript_markers: bool = False


def _parse_frame_rate(value: float | int | str | None) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (float, int)):
        return float(value)

    raw = value.strip()
    if not raw:
        return 0.0
    if "/" in raw:
        numerator_text, denominator_text = raw.split("/", 1)
        try:
            numerator = float(numerator_text)
            denominator = float(denominator_text)
        except ValueError:
            return 0.0
        if denominator == 0:
            return 0.0
        return numerator / denominator

    try:
        return float(raw)
    except ValueError:
        return 0.0


def _snap_fps(value: float | int | str | None) -> float:
    parsed = _parse_frame_rate(value)
    if parsed <= 0:
        return 29.97
    return min(STANDARD_FPS, key=lambda standard: abs(standard - parsed))


def _fps_to_frame_duration(fps: float | int | str | None) -> tuple[int, int]:
    snapped = _snap_fps(fps)
    return _FPS_RATIONAL_MAP[snapped]


def _ms_to_rational(ms: int, fps: float | int | str | None, *, min_one_frame: bool = False) -> str:
    frame_duration, timebase = _fps_to_frame_duration(fps)
    frames = round(ms * timebase / (1000 * frame_duration))
    if min_one_frame and frames <= 0:
        frames = 1
    if frames < 0:
        frames = 0
    numerator = frames * frame_duration
    return f"{numerator}/{timebase}s"


def _path_to_file_url(path: str) -> str:
    normalized = path.replace("\\", "/")
    is_windows_abs = len(normalized) >= 3 and normalized[1] == ":" and normalized[2] == "/"
    is_posix_abs = normalized.startswith("/")
    if not (is_windows_abs or is_posix_abs):
        raise ValueError(f"Expected absolute path, got: {path}")

    components = normalized.split("/")
    encoded = "/".join(quote(component, safe="") for component in components)
    if is_windows_abs:
        return f"file:///{encoded}"
    return f"file://{encoded}"


def _media_src(path: str) -> str:
    """Convert a media path to an FCPXML src attribute value.

    Absolute paths become file:// URLs (backward-compatible).
    Relative paths are URL-encoded as-is (for bundled proxy media).
    """
    normalized = path.replace("\\", "/")
    is_abs = normalized.startswith("/") or (len(normalized) >= 3 and normalized[1] == ":")
    if is_abs:
        return _path_to_file_url(path)
    components = normalized.split("/")
    return "/".join(quote(component, safe="") for component in components)

def _uid_from_path(path: str) -> str:
    return md5(path.encode("utf-8")).hexdigest().upper()


def _clip_markers(clip: FCPXMLClip, include_transcript_markers: bool) -> Iterable[ClipMarker]:
    for marker in clip.markers:
        yield marker

    if include_transcript_markers:
        for transcript in clip.transcript_markers:
            yield ClipMarker(
                start_ms=transcript.start_ms,
                end_ms=transcript.end_ms,
                note=transcript.text,
                value="standard",
            )


def _truncate(text: str, *, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit]


def generate_fcpxml(
    clips: Sequence[FCPXMLClip],
    sequence_name: str,
    options: FCPXMLWriteOptions | None = None,
) -> str:
    if not clips:
        raise ValueError("clips must not be empty")

    opts = options or FCPXMLWriteOptions()
    gap_ms = max(0, opts.gap_ms)
    sequence_fps = _snap_fps(clips[0].fps)

    fcpxml = ET.Element("fcpxml", {"version": "1.8"})
    resources = ET.SubElement(fcpxml, "resources")

    resource_index = 1
    format_by_key: dict[tuple[float, int, int], str] = {}
    asset_by_key: dict[str, str] = {}

    def ensure_format(clip: FCPXMLClip) -> str:
        nonlocal resource_index
        fps = _snap_fps(clip.fps)
        key = (fps, clip.width, clip.height)
        existing = format_by_key.get(key)
        if existing is not None:
            return existing

        fmt_id = f"r{resource_index}"
        resource_index += 1
        frame_duration, timebase = _fps_to_frame_duration(fps)
        _ = ET.SubElement(
            resources,
            "format",
            {
                "id": fmt_id,
                "frameDuration": f"{frame_duration}/{timebase}s",
                "width": str(clip.width),
                "height": str(clip.height),
                "colorSpace": "1-1-1 (Rec. 709)",
            },
        )
        format_by_key[key] = fmt_id
        return fmt_id

    for clip in clips:
        fmt_id = ensure_format(clip)
        src = _media_src(clip.file_path)
        asset_key = clip.file_path
        if asset_key in asset_by_key:
            continue

        asset_id = f"r{resource_index}"
        resource_index += 1
        asset_by_key[asset_key] = asset_id

        clip_duration_ms = max(0, clip.end_ms - clip.start_ms)
        asset = ET.SubElement(
            resources,
            "asset",
            {
                "id": asset_id,
                "uid": _uid_from_path(clip.file_path),
                "src": src,
                "start": "0s",
                "duration": _ms_to_rational(clip_duration_ms, clip.fps, min_one_frame=True),
                "hasVideo": "1" if clip.has_video else "0",
                "hasAudio": "1" if clip.has_audio else "0",
                "format": fmt_id,
                "audioSources": str(max(0, clip.audio_sources)),
                "audioChannels": str(max(0, clip.audio_channels)),
                "audioRate": "48000",
            },
        )
        _ = ET.SubElement(asset, "media-rep", {"kind": "original-media", "src": src})

    library = ET.SubElement(fcpxml, "library")
    event = ET.SubElement(library, "event", {"name": opts.event_name})
    project = ET.SubElement(event, "project", {"name": _truncate(sequence_name, limit=512)})

    sequence_attrs = {
        "format": format_by_key[(sequence_fps, clips[0].width, clips[0].height)],
        "duration": "0s",
        "tcStart": "0s",
        "tcFormat": "NDF",
        "audioLayout": "stereo",
        "audioRate": "48k",
    }
    sequence = ET.SubElement(project, "sequence", sequence_attrs)
    spine = ET.SubElement(sequence, "spine")

    timeline_ms = 0
    for index, clip in enumerate(clips):
        clip_duration_ms = max(0, clip.end_ms - clip.start_ms)
        asset_ref = asset_by_key[clip.file_path]
        offset = _ms_to_rational(timeline_ms, clip.fps)
        duration = _ms_to_rational(clip_duration_ms, clip.fps, min_one_frame=True)
        start = _ms_to_rational(max(0, clip.source_start_ms + clip.start_ms), clip.fps)

        clip_node = ET.SubElement(
            spine,
            "asset-clip",
            {
                "ref": asset_ref,
                "offset": offset,
                "name": _truncate(clip.clip_name, limit=1024),
                "duration": duration,
                "start": start,
                "audioRole": "dialogue",
            },
        )

        if opts.include_markers:
            for marker in _clip_markers(clip, opts.include_transcript_markers):
                marker_duration_ms = 0
                if marker.end_ms is not None:
                    marker_duration_ms = max(0, marker.end_ms - marker.start_ms)
                _ = ET.SubElement(
                    clip_node,
                    "marker",
                    {
                        "start": _ms_to_rational(max(0, marker.start_ms), clip.fps),
                        "duration": _ms_to_rational(marker_duration_ms, clip.fps, min_one_frame=True),
                        "value": marker.value or "standard",
                        "note": _truncate(marker.note, limit=4096),
                    },
                )

        timeline_ms += clip_duration_ms
        if gap_ms > 0 and index < len(clips) - 1:
            _ = ET.SubElement(
                spine,
                "gap",
                {
                    "offset": _ms_to_rational(timeline_ms, clip.fps),
                    "duration": _ms_to_rational(gap_ms, clip.fps, min_one_frame=True),
                },
            )
            timeline_ms += gap_ms

    sequence.set("duration", _ms_to_rational(timeline_ms, sequence_fps, min_one_frame=True))

    xml_body = ET.tostring(fcpxml, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + xml_body + "\n"
