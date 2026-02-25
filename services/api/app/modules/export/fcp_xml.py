"""FCP 7 XML (xmeml v5) generator for Premiere Pro import.

Generates a valid Final Cut Pro 7 XML file that Premiere Pro can
import via File > Import. Uses <pathurl> for media linking and
creates both video and audio tracks for each clip.
"""

import math
from typing import NotRequired, TypedDict
from urllib.parse import quote as urlquote
from xml.etree.ElementTree import Element, SubElement, tostring


class FcpClip(TypedDict):
    clip_name: str
    file_path: str  # absolute local path, e.g. /Volumes/GoogleDrive/.../video.mp4
    file_name: str
    start_ms: int
    end_ms: int
    source_duration_ms: NotRequired[int]  # total source file duration


def _path_to_url(path: str) -> str:
    """Convert an absolute filesystem path to a file:// URL."""
    # URL-encode each path component, preserve /
    parts = path.split("/")
    encoded = "/".join(urlquote(p, safe="") for p in parts)
    return f"file://localhost{encoded}"


def _ms_to_frames(ms: int, fps: int) -> int:
    return round(ms * fps / 1000.0)


def _add_rate(parent: Element, fps: int) -> None:
    rate = SubElement(parent, "rate")
    SubElement(rate, "timebase").text = str(fps)
    # NTSC for 29.97/59.94; we round to int so this is always FALSE
    SubElement(rate, "ntsc").text = "FALSE"


def generate_fcp_xml(
    clips: list[FcpClip],
    title: str,
    frame_rate: float,
) -> str:
    """Generate FCP 7 XML (xmeml v5) string."""
    fps = round(frame_rate)
    if fps <= 0:
        fps = 30

    # Calculate total timeline duration
    total_duration_ms = sum(c["end_ms"] - c["start_ms"] for c in clips)
    total_frames = _ms_to_frames(total_duration_ms, fps)

    # Root
    xmeml = Element("xmeml", version="5")
    seq = SubElement(xmeml, "sequence", id="sequence-1")
    SubElement(seq, "name").text = title
    SubElement(seq, "duration").text = str(total_frames)
    _add_rate(seq, fps)

    # Timecode
    tc = SubElement(seq, "timecode")
    _add_rate(tc, fps)
    SubElement(tc, "string").text = "00:00:00:00"
    SubElement(tc, "frame").text = "0"
    SubElement(tc, "displayformat").text = "NDF"

    media = SubElement(seq, "media")

    # Video tracks container
    video_section = SubElement(media, "video")
    v_track = SubElement(video_section, "track")

    # Audio tracks container
    audio_section = SubElement(media, "audio")
    a_track = SubElement(audio_section, "track")

    record_offset_ms = 0
    file_elements: dict[str, bool] = {}  # track which file IDs are already defined

    for i, clip in enumerate(clips, start=1):
        duration_ms = clip["end_ms"] - clip["start_ms"]
        src_duration_ms = clip.get("source_duration_ms", 0) or duration_ms * 2
        src_duration_frames = _ms_to_frames(src_duration_ms, fps)

        src_in = _ms_to_frames(clip["start_ms"], fps)
        src_out = _ms_to_frames(clip["end_ms"], fps)
        rec_in = _ms_to_frames(record_offset_ms, fps)
        rec_out = _ms_to_frames(record_offset_ms + duration_ms, fps)

        file_id = f"file-{i}"
        pathurl = _path_to_url(clip["file_path"])

        # --- Video clip item ---
        v_item = SubElement(v_track, "clipitem", id=f"clipitem-v-{i}")
        SubElement(v_item, "name").text = clip["clip_name"]
        SubElement(v_item, "duration").text = str(src_duration_frames)
        _add_rate(v_item, fps)
        SubElement(v_item, "start").text = str(rec_in)
        SubElement(v_item, "end").text = str(rec_out)
        SubElement(v_item, "in").text = str(src_in)
        SubElement(v_item, "out").text = str(src_out)

        # File element (full definition on first occurrence)
        if file_id not in file_elements:
            f_el = SubElement(v_item, "file", id=file_id)
            SubElement(f_el, "name").text = clip["file_name"]
            SubElement(f_el, "pathurl").text = pathurl
            SubElement(f_el, "duration").text = str(src_duration_frames)
            _add_rate(f_el, fps)
            f_media = SubElement(f_el, "media")
            f_vid = SubElement(f_media, "video")
            v_chars = SubElement(f_vid, "samplecharacteristics")
            SubElement(v_chars, "width").text = "1920"
            SubElement(v_chars, "height").text = "1080"
            SubElement(v_chars, "anamorphic").text = "FALSE"
            SubElement(v_chars, "pixelaspectratio").text = "square"
            SubElement(v_chars, "fielddominance").text = "none"
            f_aud = SubElement(f_media, "audio")
            a_chars = SubElement(f_aud, "samplecharacteristics")
            SubElement(a_chars, "depth").text = "16"
            SubElement(a_chars, "samplerate").text = "48000"
            file_elements[file_id] = True
        else:
            SubElement(v_item, "file", id=file_id)

        # Video source track reference
        v_src = SubElement(v_item, "sourcetrack")
        SubElement(v_src, "mediatype").text = "video"

        # --- Audio clip item (linked to same file) ---
        a_item = SubElement(a_track, "clipitem", id=f"clipitem-a-{i}")
        SubElement(a_item, "name").text = clip["clip_name"]
        SubElement(a_item, "duration").text = str(src_duration_frames)
        _add_rate(a_item, fps)
        SubElement(a_item, "start").text = str(rec_in)
        SubElement(a_item, "end").text = str(rec_out)
        SubElement(a_item, "in").text = str(src_in)
        SubElement(a_item, "out").text = str(src_out)
        # Reference the same file (no children = reference by ID)
        SubElement(a_item, "file", id=file_id)
        a_src = SubElement(a_item, "sourcetrack")
        SubElement(a_src, "mediatype").text = "audio"
        SubElement(a_src, "trackindex").text = "1"

        record_offset_ms += duration_ms

    xml_bytes = tostring(xmeml, encoding="unicode")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!DOCTYPE xmeml>\n"
        + xml_bytes
        + "\n"
    )
