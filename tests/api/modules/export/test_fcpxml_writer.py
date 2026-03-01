from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import re
import sys
from typing import Protocol, cast
import xml.etree.ElementTree as ET

import pytest


class _ClipMarkerCtor(Protocol):
    def __call__(self, start_ms: int, end_ms: int | None = None, note: str = "", value: str = "standard") -> object: ...


class _TranscriptMarkerCtor(Protocol):
    def __call__(self, start_ms: int, end_ms: int, text: str) -> object: ...


class _ClipCtor(Protocol):
    def __call__(
        self,
        clip_name: str,
        file_path: str,
        start_ms: int,
        end_ms: int,
        fps: float | int | str | None = None,
        width: int = 1920,
        height: int = 1080,
        has_video: bool = True,
        has_audio: bool = True,
        audio_sources: int = 1,
        audio_channels: int = 2,
        source_start_ms: int = 0,
        markers: tuple[object, ...] = (),
        transcript_markers: tuple[object, ...] = (),
    ) -> object: ...


class _OptionsCtor(Protocol):
    def __call__(
        self,
        event_name: str = "Heimdex Export",
        gap_ms: int = 0,
        include_markers: bool = True,
        include_transcript_markers: bool = False,
    ) -> object: ...


class _GenerateFn(Protocol):
    def __call__(self, clips: list[object], sequence_name: str, options: object | None = None) -> str: ...


class _ParseRateFn(Protocol):
    def __call__(self, value: float | int | str | None) -> float: ...


class _SnapFpsFn(Protocol):
    def __call__(self, value: float | int | str | None) -> float: ...


class _MsToRationalFn(Protocol):
    def __call__(self, ms: int, fps: float | int | str | None, min_one_frame: bool = False) -> str: ...


MODULE_PATH = (
    Path(__file__).resolve().parents[4]
    / "services"
    / "api"
    / "app"
    / "modules"
    / "export"
    / "fcpxml_writer.py"
)
SPEC = spec_from_file_location("fcpxml_writer", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
MODULE = module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

FCPXMLClip = cast(_ClipCtor, getattr(MODULE, "FCPXMLClip"))
ClipMarker = cast(_ClipMarkerCtor, getattr(MODULE, "ClipMarker"))
TranscriptMarker = cast(_TranscriptMarkerCtor, getattr(MODULE, "TranscriptMarker"))
FCPXMLWriteOptions = cast(_OptionsCtor, getattr(MODULE, "FCPXMLWriteOptions"))
generate_fcpxml = cast(_GenerateFn, getattr(MODULE, "generate_fcpxml"))
_parse_frame_rate = cast(_ParseRateFn, getattr(MODULE, "_parse_frame_rate"))
_snap_fps = cast(_SnapFpsFn, getattr(MODULE, "_snap_fps"))
_ms_to_rational = cast(_MsToRationalFn, getattr(MODULE, "_ms_to_rational"))


def _parse_xml(xml_text: str) -> ET.Element:
    return ET.fromstring(xml_text)


def _assets(root: ET.Element) -> list[ET.Element]:
    resources = root.find("resources")
    assert resources is not None
    return resources.findall("asset")


def _formats(root: ET.Element) -> list[ET.Element]:
    resources = root.find("resources")
    assert resources is not None
    return resources.findall("format")


def _spine(root: ET.Element) -> ET.Element:
    node = root.find("./library/event/project/sequence/spine")
    assert node is not None
    return node


def test_single_clip_2997fps() -> None:
    clip = FCPXMLClip(
        clip_name="Intro",
        file_path="/Volumes/Drive/video.mp4",
        start_ms=0,
        end_ms=1000,
        fps=29.97,
    )
    xml_text = generate_fcpxml([clip], "Sequence")
    root = _parse_xml(xml_text)

    assert root.attrib["version"] == "1.8"
    assert '<!DOCTYPE fcpxml>' in xml_text
    assert _formats(root)[0].attrib["frameDuration"] == "1001/30000s"
    sequence = root.find("./library/event/project/sequence")
    assert sequence is not None
    assert sequence.attrib["audioRate"] == "48k"


def test_multiple_clips_same_fps() -> None:
    clips = [
        FCPXMLClip("A", "/Volumes/Drive/a.mp4", 0, 1000, fps=29.97),
        FCPXMLClip("B", "/Volumes/Drive/b.mp4", 1000, 2500, fps=29.97),
    ]
    root = _parse_xml(generate_fcpxml(clips, "Sequence"))
    spine = _spine(root)
    asset_clips = spine.findall("asset-clip")
    assert len(asset_clips) == 2
    assert len(_formats(root)) == 1


def test_mixed_frame_rates_creates_multiple_formats() -> None:
    clips = [
        FCPXMLClip("A", "/Volumes/Drive/a.mp4", 0, 1000, fps=29.97),
        FCPXMLClip("B", "/Volumes/Drive/b.mp4", 0, 1000, fps=25.0),
    ]
    root = _parse_xml(generate_fcpxml(clips, "Sequence"))
    format_durations = {f.attrib["frameDuration"] for f in _formats(root)}
    assert "1001/30000s" in format_durations
    assert "100/2500s" in format_durations
    assert len(format_durations) == 2


def test_clip_with_markers() -> None:
    clip = FCPXMLClip(
        "Clip",
        "/Volumes/Drive/clip.mp4",
        0,
        2000,
        fps=30.0,
        markers=(ClipMarker(start_ms=500, end_ms=1000, note="midpoint"),),
    )
    root = _parse_xml(generate_fcpxml([clip], "Sequence"))
    marker = root.find("./library/event/project/sequence/spine/asset-clip/marker")
    assert marker is not None
    assert marker.attrib["note"] == "midpoint"


def test_clip_with_transcript_markers() -> None:
    clip = FCPXMLClip(
        "Clip",
        "/Volumes/Drive/clip.mp4",
        0,
        2000,
        fps=30.0,
        transcript_markers=(TranscriptMarker(start_ms=100, end_ms=300, text="hello world"),),
    )
    opts = FCPXMLWriteOptions(include_transcript_markers=True)
    root = _parse_xml(generate_fcpxml([clip], "Sequence", options=opts))
    marker = root.find("./library/event/project/sequence/spine/asset-clip/marker")
    assert marker is not None
    assert marker.attrib["note"] == "hello world"


def test_gap_between_clips() -> None:
    clips = [
        FCPXMLClip("A", "/Volumes/Drive/a.mp4", 0, 1000, fps=30.0),
        FCPXMLClip("B", "/Volumes/Drive/b.mp4", 0, 1000, fps=30.0),
    ]
    opts = FCPXMLWriteOptions(gap_ms=500)
    root = _parse_xml(generate_fcpxml(clips, "Sequence", options=opts))
    gap = _spine(root).find("gap")
    assert gap is not None
    assert gap.attrib["duration"] == _ms_to_rational(500, 30.0, min_one_frame=True)


def test_default_fps_fallback_for_zero() -> None:
    clip = FCPXMLClip("A", "/Volumes/Drive/a.mp4", 0, 1000, fps=0)
    root = _parse_xml(generate_fcpxml([clip], "Sequence"))
    assert _formats(root)[0].attrib["frameDuration"] == "1001/30000s"


def test_korean_filename_path_url_encoding() -> None:
    clip = FCPXMLClip("A", "/Volumes/드라이브/라이브커머스 세일.mp4", 0, 1000, fps=29.97)
    root = _parse_xml(generate_fcpxml([clip], "Sequence"))
    asset = _assets(root)[0]
    assert "%EB%9D%BC%EC%9D%B4%EB%B8%8C%EC%BB%A4%EB%A8%B8%EC%8A%A4%20%EC%84%B8%EC%9D%BC.mp4" in asset.attrib["src"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("30000/1001", 29.97002997002997),
        ("30", 30.0),
        ("", 0.0),
        ("1/0", 0.0),
    ],
)
def test_parse_frame_rate_edge_cases(value: str, expected: float) -> None:
    assert _parse_frame_rate(value) == expected


@pytest.mark.parametrize(
    ("measured", "snapped"),
    [
        (29.98, 29.97),
        (23.97, 23.976),
        (59.96, 59.94),
    ],
)
def test_snap_fps_non_standard_values(measured: float, snapped: float) -> None:
    assert _snap_fps(measured) == snapped


def test_ms_to_rational_frame_boundary_snapping() -> None:
    assert _ms_to_rational(1, 29.97) == "0/30000s"
    assert _ms_to_rational(17, 29.97) == "1001/30000s"


def test_empty_clips_raises_value_error() -> None:
    with pytest.raises(ValueError):
        _ = generate_fcpxml([], "Sequence")


def test_doctype_presence() -> None:
    xml_text = generate_fcpxml([FCPXMLClip("A", "/Volumes/Drive/a.mp4", 0, 1000, fps=30.0)], "Sequence")
    assert "<!DOCTYPE fcpxml>" in xml_text


def test_media_rep_presence_on_asset() -> None:
    root = _parse_xml(generate_fcpxml([FCPXMLClip("A", "/Volumes/Drive/a.mp4", 0, 1000, fps=30.0)], "Sequence"))
    media_rep = root.find("./resources/asset/media-rep")
    assert media_rep is not None
    assert media_rep.attrib["kind"] == "original-media"


def test_asset_uid_format_32_char_upper_hex() -> None:
    root = _parse_xml(generate_fcpxml([FCPXMLClip("A", "/Volumes/Drive/a.mp4", 0, 1000, fps=30.0)], "Sequence"))
    uid = _assets(root)[0].attrib["uid"]
    assert re.fullmatch(r"[A-F0-9]{32}", uid)


def test_clip_with_no_audio_sets_has_audio_zero() -> None:
    clip = FCPXMLClip("A", "/Volumes/Drive/a.mp4", 0, 1000, fps=30.0, has_audio=False)
    root = _parse_xml(generate_fcpxml([clip], "Sequence"))
    assert _assets(root)[0].attrib["hasAudio"] == "0"


def test_very_long_clip_name_and_note_are_handled() -> None:
    long_name = "N" * 4000
    long_note = "Q" * 10000
    clip = FCPXMLClip(
        clip_name=long_name,
        file_path="/Volumes/Drive/a.mp4",
        start_ms=0,
        end_ms=1000,
        fps=30.0,
        markers=(ClipMarker(start_ms=0, end_ms=100, note=long_note),),
    )
    root = _parse_xml(generate_fcpxml([clip], "Sequence"))
    asset_clip = root.find("./library/event/project/sequence/spine/asset-clip")
    marker = root.find("./library/event/project/sequence/spine/asset-clip/marker")
    assert asset_clip is not None
    assert marker is not None
    assert len(asset_clip.attrib["name"]) == 1024
    assert len(marker.attrib["note"]) == 4096


def test_sequence_audio_rate_is_48k() -> None:
    root = _parse_xml(generate_fcpxml([FCPXMLClip("A", "/Volumes/Drive/a.mp4", 0, 1000, fps=30.0)], "Sequence"))
    sequence = root.find("./library/event/project/sequence")
    assert sequence is not None
    assert sequence.attrib["audioRate"] == "48k"


def test_single_frame_duration_marker() -> None:
    clip = FCPXMLClip(
        clip_name="A",
        file_path="/Volumes/Drive/a.mp4",
        start_ms=0,
        end_ms=1000,
        fps=29.97,
        markers=(ClipMarker(start_ms=500, end_ms=500, note="one frame"),),
    )
    root = _parse_xml(generate_fcpxml([clip], "Sequence"))
    marker = root.find("./library/event/project/sequence/spine/asset-clip/marker")
    assert marker is not None
    assert marker.attrib["duration"] == "1001/30000s"


def test_asset_dedup_for_same_source_video() -> None:
    clips = [
        FCPXMLClip("A", "/Volumes/Drive/same.mp4", 0, 1000, fps=29.97),
        FCPXMLClip("B", "/Volumes/Drive/same.mp4", 1000, 2000, fps=29.97),
    ]
    root = _parse_xml(generate_fcpxml(clips, "Sequence"))
    assert len(_assets(root)) == 1
    refs = [node.attrib["ref"] for node in _spine(root).findall("asset-clip")]
    assert len(set(refs)) == 1


def test_sequence_duration_includes_gap() -> None:
    clips = [
        FCPXMLClip("A", "/Volumes/Drive/a.mp4", 0, 1000, fps=30.0),
        FCPXMLClip("B", "/Volumes/Drive/b.mp4", 0, 1000, fps=30.0),
    ]
    root = _parse_xml(generate_fcpxml(clips, "Sequence", options=FCPXMLWriteOptions(gap_ms=500)))
    sequence = root.find("./library/event/project/sequence")
    assert sequence is not None
    assert sequence.attrib["duration"] == _ms_to_rational(2500, 30.0, min_one_frame=True)


def test_markers_disabled_option() -> None:
    clip = FCPXMLClip(
        "A",
        "/Volumes/Drive/a.mp4",
        0,
        1000,
        fps=30.0,
        markers=(ClipMarker(start_ms=100, end_ms=200, note="x"),),
    )
    root = _parse_xml(generate_fcpxml([clip], "Sequence", options=FCPXMLWriteOptions(include_markers=False)))
    assert root.find("./library/event/project/sequence/spine/asset-clip/marker") is None
