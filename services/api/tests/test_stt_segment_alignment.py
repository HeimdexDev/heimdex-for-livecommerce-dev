import importlib.util
import struct
import tempfile
from pathlib import Path

from heimdex_media_contracts.scenes.merge import (
    assign_segments_to_scenes,
    aggregate_transcript,
)
from heimdex_media_contracts.scenes.schemas import SceneBoundary
from heimdex_media_contracts.speech.schemas import SpeechSegment

_stt_module_path = (
    Path(__file__).resolve().parents[2] / "drive-stt-worker" / "src" / "tasks" / "stt.py"
)
_spec = importlib.util.spec_from_file_location("_stt_tasks_for_test", _stt_module_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_get_audio_duration_seconds = _mod._get_audio_duration_seconds
_align_segments_to_scenes = _mod._align_segments_to_scenes
_build_scenes_no_speech = _mod._build_scenes_no_speech


def _make_boundary(scene_id: str, index: int, start_ms: int, end_ms: int) -> SceneBoundary:
    return SceneBoundary(
        scene_id=scene_id,
        index=index,
        start_ms=start_ms,
        end_ms=end_ms,
        keyframe_timestamp_ms=(start_ms + end_ms) // 2,
    )


def _make_segment(start: float, end: float, text: str) -> SpeechSegment:
    return SpeechSegment(start=start, end=end, text=text, confidence=1.0)


def _make_wav_file(duration_seconds: float, sample_rate: int = 16000) -> Path:
    num_frames = int(duration_seconds * sample_rate)
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    num_channels = 1
    sample_width = 2
    data_size = num_frames * num_channels * sample_width
    tmp.write(b"RIFF")
    tmp.write(struct.pack("<I", 36 + data_size))
    tmp.write(b"WAVE")
    tmp.write(b"fmt ")
    tmp.write(struct.pack("<I", 16))
    tmp.write(struct.pack("<H", 1))
    tmp.write(struct.pack("<H", num_channels))
    tmp.write(struct.pack("<I", sample_rate))
    tmp.write(struct.pack("<I", sample_rate * num_channels * sample_width))
    tmp.write(struct.pack("<H", num_channels * sample_width))
    tmp.write(struct.pack("<H", sample_width * 8))
    tmp.write(b"data")
    tmp.write(struct.pack("<I", data_size))
    tmp.write(b"\x00" * data_size)
    tmp.close()
    return Path(tmp.name)


class TestAssignSegmentsToScenes:
    def test_segment_fully_within_scene(self):
        scenes = [_make_boundary("v_scene_0", 0, 0, 10000)]
        segments = [_make_segment(2.0, 5.0, "hello")]
        result = assign_segments_to_scenes(scenes, segments)
        assert len(result["v_scene_0"]) == 1
        assert result["v_scene_0"][0].text == "hello"

    def test_segment_spanning_two_scenes_assigned_to_larger_overlap(self):
        scenes = [
            _make_boundary("v_scene_0", 0, 0, 10000),
            _make_boundary("v_scene_1", 1, 10000, 20000),
        ]
        segments = [_make_segment(8.0, 15.0, "spanning")]
        result = assign_segments_to_scenes(scenes, segments)
        assert len(result["v_scene_1"]) == 1
        assert len(result["v_scene_0"]) == 0

    def test_segment_before_all_scenes_dropped(self):
        scenes = [_make_boundary("v_scene_0", 0, 5000, 10000)]
        segments = [_make_segment(0.0, 1.0, "early")]
        result = assign_segments_to_scenes(scenes, segments)
        assert len(result["v_scene_0"]) == 0

    def test_segment_after_all_scenes_dropped(self):
        scenes = [_make_boundary("v_scene_0", 0, 0, 5000)]
        segments = [_make_segment(10.0, 12.0, "late")]
        result = assign_segments_to_scenes(scenes, segments)
        assert len(result["v_scene_0"]) == 0

    def test_no_segments_empty_assignment(self):
        scenes = [_make_boundary("v_scene_0", 0, 0, 10000)]
        result = assign_segments_to_scenes(scenes, [])
        assert result["v_scene_0"] == []

    def test_multiple_segments_same_scene_concatenated(self):
        scenes = [_make_boundary("v_scene_0", 0, 0, 30000)]
        segments = [
            _make_segment(1.0, 5.0, "first"),
            _make_segment(10.0, 15.0, "second"),
            _make_segment(20.0, 25.0, "third"),
        ]
        result = assign_segments_to_scenes(scenes, segments)
        assigned = result["v_scene_0"]
        assert len(assigned) == 3
        transcript = aggregate_transcript(assigned)
        assert transcript == "first second third"

    def test_segments_sorted_by_start_within_scene(self):
        scenes = [_make_boundary("v_scene_0", 0, 0, 30000)]
        segments = [
            _make_segment(20.0, 25.0, "late"),
            _make_segment(1.0, 5.0, "early"),
        ]
        result = assign_segments_to_scenes(scenes, segments)
        assigned = result["v_scene_0"]
        assert assigned[0].text == "early"
        assert assigned[1].text == "late"

    def test_three_scenes_correct_distribution(self):
        scenes = [
            _make_boundary("v_scene_0", 0, 0, 10000),
            _make_boundary("v_scene_1", 1, 10000, 20000),
            _make_boundary("v_scene_2", 2, 20000, 30000),
        ]
        segments = [
            _make_segment(2.0, 8.0, "in scene 0"),
            _make_segment(12.0, 18.0, "in scene 1"),
            _make_segment(22.0, 28.0, "in scene 2"),
        ]
        result = assign_segments_to_scenes(scenes, segments)
        assert len(result["v_scene_0"]) == 1
        assert len(result["v_scene_1"]) == 1
        assert len(result["v_scene_2"]) == 1
        assert result["v_scene_0"][0].text == "in scene 0"
        assert result["v_scene_1"][0].text == "in scene 1"
        assert result["v_scene_2"][0].text == "in scene 2"


class TestAlignSegmentsToScenesWrapper:
    def test_produces_transcript_raw_and_count(self):
        scenes = [
            {"scene_id": "v_scene_0", "index": 0, "start_ms": 0, "end_ms": 10000, "keyframe_timestamp_ms": 5000},
        ]
        segments = [_make_segment(1.0, 3.0, "hello"), _make_segment(4.0, 6.0, "world")]
        result = _align_segments_to_scenes(scenes, segments)
        assert result[0]["transcript_raw"] == "hello world"
        assert result[0]["speech_segment_count"] == 2

    def test_preserves_existing_fields(self):
        scenes = [
            {
                "scene_id": "v_scene_0", "index": 0, "start_ms": 0, "end_ms": 10000,
                "keyframe_timestamp_ms": 5000, "ocr_text_raw": "price tag",
                "ocr_char_count": 9, "source_type": "gdrive",
            },
        ]
        segments = [_make_segment(1.0, 3.0, "speech")]
        result = _align_segments_to_scenes(scenes, segments)
        assert result[0]["ocr_text_raw"] == "price tag"
        assert result[0]["ocr_char_count"] == 9
        assert result[0]["source_type"] == "gdrive"


class TestBuildScenesNoSpeech:
    def test_sets_empty_transcript(self):
        scenes = [
            {"scene_id": "v_scene_0", "index": 0, "start_ms": 0, "end_ms": 5000},
        ]
        result = _build_scenes_no_speech(scenes)
        assert result[0]["transcript_raw"] == ""
        assert result[0]["speech_segment_count"] == 0

    def test_preserves_other_fields(self):
        scenes = [
            {"scene_id": "v_scene_0", "index": 0, "ocr_text_raw": "text"},
        ]
        result = _build_scenes_no_speech(scenes)
        assert result[0]["ocr_text_raw"] == "text"


class TestGetAudioDurationSeconds:
    def test_reads_wav_duration(self):
        wav_path = _make_wav_file(10.0)
        try:
            duration = _get_audio_duration_seconds(wav_path)
            assert abs(duration - 10.0) < 0.01
        finally:
            wav_path.unlink()

    def test_short_audio(self):
        wav_path = _make_wav_file(0.5)
        try:
            duration = _get_audio_duration_seconds(wav_path)
            assert abs(duration - 0.5) < 0.01
        finally:
            wav_path.unlink()

    def test_long_audio(self):
        wav_path = _make_wav_file(3600.0, sample_rate=16000)
        try:
            duration = _get_audio_duration_seconds(wav_path)
            assert abs(duration - 3600.0) < 0.1
        finally:
            wav_path.unlink()
