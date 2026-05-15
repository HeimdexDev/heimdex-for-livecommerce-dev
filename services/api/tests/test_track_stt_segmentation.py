"""Unit tests for the live-block segmenter.

Pure-function tests over synthetic OS scene dicts. Cover:

* Empty input → empty output
* All-silent video → no blocks
* All-live video → one block spanning everything
* Intro/live/outro pattern (the canonical livecommerce shape) → one
  middle block
* Each of the three live signals (``speaker_transcript``,
  ``transcript_raw``, ``speech_segment_count``) independently flags
  a scene as live
* ``min_block_ms`` drops short live bursts but keeps real ones
* ``scene_ids_in_live_blocks`` returns the expected allowlist
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.shorts_auto_product.track_stt.segmentation import (
    LiveBlock,
    PartitionSummary,
    partition_live_blocks,
    scene_ids_in_live_blocks,
    summarize,
)


# ---------- helpers ----------


def _scene(
    scene_id: str,
    start_ms: int,
    end_ms: int,
    *,
    speaker_transcript: str = "",
    transcript_raw: str = "",
    speech_segment_count: int = 0,
) -> dict[str, Any]:
    return {
        "scene_id": scene_id,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "speaker_transcript": speaker_transcript,
        "transcript_raw": transcript_raw,
        "speech_segment_count": speech_segment_count,
    }


# ---------- partition_live_blocks ----------


def test_empty_input_returns_empty():
    assert partition_live_blocks([]) == []


def test_all_silent_returns_no_blocks():
    scenes = [_scene("s1", 0, 1000), _scene("s2", 1000, 2000)]
    assert partition_live_blocks(scenes) == []


def test_all_live_returns_single_block():
    scenes = [
        _scene("s1", 0, 1000, speaker_transcript="hello"),
        _scene("s2", 1000, 2000, speaker_transcript="world"),
    ]
    blocks = partition_live_blocks(scenes)
    assert len(blocks) == 1
    assert blocks[0] == LiveBlock(
        start_ms=0, end_ms=2000, scene_ids=("s1", "s2")
    )


def test_intro_live_outro_pattern():
    """Canonical livecommerce shape: silent b-roll, host talks, silent b-roll."""
    scenes = [
        # Silent intro
        _scene("intro_a", 0, 1000),
        _scene("intro_b", 1000, 2000),
        _scene("intro_c", 2000, 3000),
        # Live host pitch
        _scene("live_a", 3000, 4000, speaker_transcript="안녕하세요"),
        _scene("live_b", 4000, 5000, speaker_transcript="이 제품은"),
        # Silent outro
        _scene("outro_a", 5000, 6000),
        _scene("outro_b", 6000, 7000),
    ]
    blocks = partition_live_blocks(scenes)
    assert len(blocks) == 1
    assert blocks[0] == LiveBlock(
        start_ms=3000, end_ms=5000, scene_ids=("live_a", "live_b")
    )


def test_multiple_live_blocks_separated_by_silence():
    """Two host pitches with a silent interlude between them."""
    scenes = [
        _scene("a", 0, 1000, speaker_transcript="block1"),
        _scene("b", 1000, 2000, speaker_transcript="block1"),
        _scene("c", 2000, 3000),
        _scene("d", 3000, 4000),
        _scene("e", 4000, 5000, speaker_transcript="block2"),
    ]
    blocks = partition_live_blocks(scenes)
    assert len(blocks) == 2
    assert blocks[0].scene_ids == ("a", "b")
    assert blocks[1].scene_ids == ("e",)


def test_speaker_transcript_signal_only():
    scenes = [_scene("s1", 0, 1000, speaker_transcript="x")]
    assert len(partition_live_blocks(scenes)) == 1


def test_transcript_raw_signal_only():
    scenes = [_scene("s1", 0, 1000, transcript_raw="x")]
    assert len(partition_live_blocks(scenes)) == 1


def test_speech_segment_count_signal_only():
    scenes = [_scene("s1", 0, 1000, speech_segment_count=3)]
    assert len(partition_live_blocks(scenes)) == 1


def test_whitespace_only_transcript_is_silent():
    """Empty string after strip — not live."""
    scenes = [_scene("s1", 0, 1000, speaker_transcript="   \n   ")]
    assert partition_live_blocks(scenes) == []


def test_zero_speech_segment_count_is_silent():
    scenes = [_scene("s1", 0, 1000, speech_segment_count=0)]
    assert partition_live_blocks(scenes) == []


def test_min_block_ms_drops_short_blocks():
    scenes = [
        _scene("burst", 0, 500, speaker_transcript="oops"),  # 500ms — short
        _scene("silent", 500, 1500),
        _scene("real_a", 1500, 3500, speaker_transcript="hi"),  # 2000ms
        _scene("real_b", 3500, 5500, speaker_transcript="bye"),
    ]
    blocks = partition_live_blocks(scenes, min_block_ms=1000)
    assert len(blocks) == 1
    assert blocks[0].scene_ids == ("real_a", "real_b")


def test_min_block_ms_zero_keeps_everything():
    scenes = [
        _scene("burst", 0, 500, speaker_transcript="x"),
        _scene("silent", 500, 1500),
    ]
    blocks = partition_live_blocks(scenes, min_block_ms=0)
    assert len(blocks) == 1


def test_scene_without_scene_id_is_skipped():
    """Defensive: a malformed OS doc without scene_id shouldn't crash."""
    scenes = [
        {"start_ms": 0, "end_ms": 1000, "speaker_transcript": "hi"},
        _scene("s2", 1000, 2000, speaker_transcript="ok"),
    ]
    blocks = partition_live_blocks(scenes)
    assert len(blocks) == 1
    assert blocks[0].scene_ids == ("s2",)


def test_live_block_properties():
    block = LiveBlock(start_ms=1000, end_ms=4000, scene_ids=("a", "b", "c"))
    assert block.duration_ms == 3000
    assert block.scene_count == 3


# ---------- summarize ----------


def test_summarize_uniform_intro_live_outro():
    """Mirrors the gd_75f4fab4913c2bb1 shape: 80% excluded."""
    scenes = (
        [_scene(f"intro_{i}", i * 100, (i + 1) * 100) for i in range(8)]
        + [
            _scene(f"live_{i}", (8 + i) * 100, (9 + i) * 100, speaker_transcript="x")
            for i in range(2)
        ]
        + [_scene(f"outro_{i}", (10 + i) * 100, (11 + i) * 100) for i in range(10)]
    )
    blocks = partition_live_blocks(scenes)
    sm = summarize(scenes, blocks)

    assert sm.total_scenes == 20
    assert sm.live_scenes == 2
    assert sm.excluded_scenes == 18
    assert sm.live_block_count == 1
    assert sm.total_ms == 2000
    assert sm.live_total_ms == 200
    assert sm.longest_live_block_ms == 200
    assert sm.exclusion_pct == pytest.approx(90.0)


def test_summarize_empty_input_returns_zeros():
    sm = summarize([], [])
    assert sm == PartitionSummary(
        total_scenes=0,
        live_scenes=0,
        excluded_scenes=0,
        live_block_count=0,
        total_ms=0,
        live_total_ms=0,
        longest_live_block_ms=0,
    )
    assert sm.exclusion_pct == 0.0


# ---------- scene_ids_in_live_blocks ----------


def test_scene_ids_in_live_blocks_flattens_correctly():
    blocks = [
        LiveBlock(start_ms=0, end_ms=1000, scene_ids=("a", "b")),
        LiveBlock(start_ms=2000, end_ms=3000, scene_ids=("c",)),
    ]
    assert scene_ids_in_live_blocks(blocks) == frozenset({"a", "b", "c"})


def test_scene_ids_in_live_blocks_empty():
    assert scene_ids_in_live_blocks([]) == frozenset()
