import importlib.util
from pathlib import Path

from heimdex_media_contracts.speech.schemas import SpeechSegment

_stt_module_path = (
    Path(__file__).resolve().parents[2] / "drive-stt-worker" / "src" / "tasks" / "stt.py"
)
_spec = importlib.util.spec_from_file_location("_stt_payload_for_test", _stt_module_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_align_segments_to_scenes = _mod._align_segments_to_scenes
_build_scenes_no_speech = _mod._build_scenes_no_speech


def _make_segment(start: float, end: float, text: str) -> SpeechSegment:
    return SpeechSegment(start=start, end=end, text=text, confidence=1.0)


class TestSttIngestPayload:
    def test_transcript_raw_from_alignment(self):
        scenes = [
            {"scene_id": "v_scene_0", "index": 0, "start_ms": 0, "end_ms": 10000, "keyframe_timestamp_ms": 5000},
        ]
        segments = [_make_segment(1.0, 4.0, "hello world")]
        result = _align_segments_to_scenes(scenes, segments)
        assert result[0]["transcript_raw"] == "hello world"

    def test_speech_segment_count_matches(self):
        scenes = [
            {"scene_id": "v_scene_0", "index": 0, "start_ms": 0, "end_ms": 30000, "keyframe_timestamp_ms": 15000},
        ]
        segments = [
            _make_segment(1.0, 5.0, "a"),
            _make_segment(10.0, 15.0, "b"),
            _make_segment(20.0, 25.0, "c"),
        ]
        result = _align_segments_to_scenes(scenes, segments)
        assert result[0]["speech_segment_count"] == 3

    def test_ocr_fields_preserved(self):
        scenes = [
            {
                "scene_id": "v_scene_0", "index": 0, "start_ms": 0, "end_ms": 10000,
                "keyframe_timestamp_ms": 5000,
                "ocr_text_raw": "29,900원", "ocr_char_count": 7,
            },
        ]
        segments = [_make_segment(1.0, 3.0, "speech text")]
        result = _align_segments_to_scenes(scenes, segments)
        assert result[0]["ocr_text_raw"] == "29,900원"
        assert result[0]["ocr_char_count"] == 7
        assert result[0]["transcript_raw"] == "speech text"

    def test_no_segments_empty_transcript(self):
        scenes = [
            {"scene_id": "v_scene_0", "index": 0, "start_ms": 0, "end_ms": 5000, "keyframe_timestamp_ms": 2500},
        ]
        result = _build_scenes_no_speech(scenes)
        assert result[0]["transcript_raw"] == ""
        assert result[0]["speech_segment_count"] == 0

    def test_does_not_mutate_original_scenes(self):
        original = {"scene_id": "v_scene_0", "index": 0, "start_ms": 0, "end_ms": 10000, "keyframe_timestamp_ms": 5000}
        scenes = [original]
        segments = [_make_segment(1.0, 3.0, "text")]
        result = _align_segments_to_scenes(scenes, segments)
        assert "transcript_raw" not in original
        assert result[0]["transcript_raw"] == "text"
