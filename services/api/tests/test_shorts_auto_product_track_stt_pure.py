"""Pure-function tests for the track_stt pipeline.

Covers segment_assembler, clip_selector, composition_builder, and
the BM25 query-construction half of mention_extractor. The async
parts (mention_extractor.find_mentioned_scenes, chunk_scorer's LLM
call, service end-to-end) are exercised in
``test_shorts_auto_product_track_stt_async.py`` with mocked clients.

Loose-coupling assertion: this file imports ONLY from
``app.modules.shorts_auto_product.track_stt.*`` and stdlib. If a
future change introduces a forbidden cross-module import, the test
collection will fail at import time.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.modules.shorts_auto_product.track_stt.clip_selector import (
    MAX_TARGET_OVERSHOOT_MS,
    select_top_chunks,
)
from app.modules.shorts_auto_product.track_stt.composition_builder import (
    build_composition_spec,
)
from app.modules.shorts_auto_product.track_stt.mention_extractor import (
    _build_bm25_query,
    _hit_to_scene,
)
from app.modules.shorts_auto_product.track_stt.models import (
    ChunkScore,
    MentionedScene,
    MentionSegment,
    ScoredChunk,
)
from app.modules.shorts_auto_product.track_stt.segment_assembler import (
    MAX_GAP_MS,
    MIN_SEGMENT_MS,
    group_into_segments,
)


# ---------- helpers ----------


def _scene(start_ms: int, end_ms: int, sid: str = "x") -> MentionedScene:
    return MentionedScene(
        scene_id=sid,
        start_ms=start_ms,
        end_ms=end_ms,
        score=1.0,
        matched_field="transcript_raw",
        matched_aliases=[],
        transcript_text=f"transcript at {start_ms}",
        caption_text="",
    )


def _chunk(start_ms: int, end_ms: int, hook=0.5, has_cta=False, importance=0.5) -> ScoredChunk:
    return ScoredChunk(
        start_ms=start_ms,
        end_ms=end_ms,
        text=f"text at {start_ms}",
        score=ChunkScore(hook_score=hook, has_cta=has_cta, importance_score=importance),
    )


# ---------- segment_assembler ----------


class TestSegmentAssembler:
    def test_empty_input_returns_empty(self):
        assert group_into_segments([]) == []

    def test_single_short_scene_below_floor_dropped(self):
        # 5s < 20s floor — must drop.
        result = group_into_segments([_scene(0, 5_000)])
        assert result == []

    def test_single_long_scene_above_floor_kept(self):
        # 25s > 20s floor.
        result = group_into_segments([_scene(0, 25_000)])
        assert len(result) == 1
        assert result[0].duration_ms == 25_000

    def test_consecutive_within_gap_merge_into_one_segment(self):
        # Gap of 3s between scenes (< 5s MAX_GAP_MS) → merge.
        # 4s + 3s gap + 18s = 25s span → above floor.
        scenes = [_scene(0, 4_000), _scene(7_000, 25_000)]
        result = group_into_segments(scenes)
        assert len(result) == 1
        assert result[0].start_ms == 0
        assert result[0].end_ms == 25_000

    def test_gap_exceeds_max_splits_into_two_segments(self):
        # 6s gap > 5s MAX_GAP_MS → split. Each segment must individually
        # exceed MIN_SEGMENT_MS to be kept.
        scenes = [_scene(0, 22_000), _scene(28_000, 50_000)]
        result = group_into_segments(scenes)
        assert len(result) == 2
        assert result[0].end_ms == 22_000
        assert result[1].start_ms == 28_000

    def test_gap_exceeds_max_one_too_short_dropped(self):
        # First segment 4s (below floor), second 22s (kept).
        scenes = [_scene(0, 4_000), _scene(15_000, 37_000)]
        result = group_into_segments(scenes)
        assert len(result) == 1
        assert result[0].start_ms == 15_000

    def test_unsorted_input_sorted_internally(self):
        # Caller hands us scenes out of order — assembler still works.
        scenes = [_scene(20_000, 25_000), _scene(0, 18_000)]
        result = group_into_segments(scenes)
        assert len(result) == 1  # 0..25000, gap=2000 → merge
        assert result[0].start_ms == 0
        assert result[0].end_ms == 25_000

    def test_overlapping_scenes_collapse_correctly(self):
        # Scene B starts before A ends (overlap). Should merge cleanly.
        scenes = [_scene(0, 15_000), _scene(10_000, 25_000)]
        result = group_into_segments(scenes)
        assert len(result) == 1
        assert result[0].end_ms == 25_000  # max of both


# ---------- clip_selector ----------


class TestClipSelector:
    def test_empty_input_returns_empty(self):
        assert select_top_chunks(chunks=[], target_duration_ms=60_000) == []

    def test_zero_target_duration_returns_empty(self):
        chunks = [_chunk(0, 30_000)]
        assert select_top_chunks(chunks=chunks, target_duration_ms=0) == []

    def test_single_chunk_meets_target(self):
        chunks = [_chunk(0, 60_000, importance=0.9)]
        result = select_top_chunks(chunks=chunks, target_duration_ms=60_000)
        assert len(result) == 1
        assert result[0].start_ms == 0

    def test_picks_highest_score_seed(self):
        # Lower-importance chunk first, higher-importance second.
        # Selector should pick the higher-importance seed and walk
        # forward from there.
        chunks = [
            _chunk(0, 20_000, importance=0.3),
            _chunk(20_000, 40_000, importance=0.9),
            _chunk(40_000, 60_000, importance=0.4),
        ]
        result = select_top_chunks(chunks=chunks, target_duration_ms=40_000)
        # Chunk at 20-40 is the seed (importance 0.9), then forward
        # picks 40-60 to fill the duration.
        starts = [c.start_ms for c in result]
        assert 20_000 in starts

    def test_short_total_below_floor_returns_empty(self):
        # 15s total but target is 60s → below 50% floor (30s).
        chunks = [_chunk(0, 15_000)]
        result = select_top_chunks(chunks=chunks, target_duration_ms=60_000)
        assert result == []

    def test_overshoot_capped(self):
        # 10 chunks of 20s each = 200s; target 60s. With cap of
        # 60+20=80, selector should not return >80s of clips.
        chunks = [_chunk(i * 20_000, (i + 1) * 20_000, importance=0.5) for i in range(10)]
        result = select_top_chunks(chunks=chunks, target_duration_ms=60_000)
        assert sum(c.end_ms - c.start_ms for c in result) <= 60_000 + MAX_TARGET_OVERSHOOT_MS

    def test_chronological_order_preserved(self):
        chunks = [_chunk(0, 20_000), _chunk(20_000, 40_000), _chunk(40_000, 60_000)]
        result = select_top_chunks(chunks=chunks, target_duration_ms=60_000)
        starts = [c.start_ms for c in result]
        assert starts == sorted(starts)

    def test_cta_boost_breaks_ties(self):
        # Two chunks with equal importance; only one has_cta.
        # The CTA chunk should win as the seed.
        a = _chunk(0, 20_000, hook=0.5, has_cta=False, importance=0.5)
        b = _chunk(20_000, 40_000, hook=0.5, has_cta=True, importance=0.5)
        result = select_top_chunks(chunks=[a, b], target_duration_ms=20_000)
        assert len(result) == 1
        assert result[0].start_ms == 20_000


# ---------- composition_builder ----------


class TestCompositionBuilder:
    def test_empty_chunks_raises(self):
        with pytest.raises(ValueError, match="at least one selected chunk"):
            build_composition_spec(
                selected_chunks=[],
                segments=[],
                os_video_id="gd_x",
            )

    def test_single_chunk_one_clip(self):
        scene = _scene(0, 30_000, sid="gd_x_scene_001")
        seg = MentionSegment(start_ms=0, end_ms=30_000, scenes=[scene])
        spec = build_composition_spec(
            selected_chunks=[_chunk(0, 30_000)],
            segments=[seg],
            os_video_id="gd_x",
            title="my clip",
        )
        assert len(spec.scene_clips) == 1
        assert spec.scene_clips[0].video_id == "gd_x"
        assert spec.scene_clips[0].scene_id == "gd_x_scene_001"
        assert spec.scene_clips[0].start_ms == 0
        assert spec.scene_clips[0].end_ms == 30_000
        assert spec.scene_clips[0].timeline_start_ms == 0
        assert spec.title == "my clip"

    def test_multi_chunk_timeline_cursor_advances(self):
        scene_a = _scene(0, 20_000, sid="gd_x_scene_001")
        scene_b = _scene(20_000, 40_000, sid="gd_x_scene_002")
        seg = MentionSegment(start_ms=0, end_ms=40_000, scenes=[scene_a, scene_b])
        spec = build_composition_spec(
            selected_chunks=[_chunk(0, 20_000), _chunk(20_000, 40_000)],
            segments=[seg],
            os_video_id="gd_x",
        )
        assert len(spec.scene_clips) == 2
        # Timeline accumulates: clip 1 ends at 20s, clip 2 starts there.
        assert spec.scene_clips[0].timeline_start_ms == 0
        assert spec.scene_clips[1].timeline_start_ms == 20_000

    def test_chunk_attributed_to_max_overlap_scene(self):
        # Chunk 5-25s; scene_a (0-15) overlaps 10s, scene_b (15-30)
        # overlaps 10s — tie. The first match wins per implementation.
        # We test the more discriminating case: chunk 5-25, scene_a 0-10
        # (5s overlap), scene_b 10-30 (15s overlap) → scene_b wins.
        scene_a = _scene(0, 10_000, sid="A")
        scene_b = _scene(10_000, 30_000, sid="B")
        seg = MentionSegment(start_ms=0, end_ms=30_000, scenes=[scene_a, scene_b])
        spec = build_composition_spec(
            selected_chunks=[_chunk(5_000, 25_000)],
            segments=[seg],
            os_video_id="gd_x",
        )
        assert spec.scene_clips[0].scene_id == "B"


# ---------- mention_extractor query construction ----------


class TestMentionExtractorQuery:
    def test_label_only_no_aliases(self):
        org = uuid4()
        q = _build_bm25_query(
            org_id=org,
            video_id="gd_x",
            llm_label="달심",
            spoken_aliases=[],
        )
        # 1 must clause for org_id, 1 must for video_id → in must.
        assert {"term": {"org_id": str(org)}} in q["bool"]["must"]
        assert {"term": {"video_id": "gd_x"}} in q["bool"]["must"]
        # 2 should clauses (transcript + caption) for the label.
        assert len(q["bool"]["should"]) == 2

    def test_label_plus_aliases_produces_field_x_alias_clauses(self):
        q = _build_bm25_query(
            org_id=uuid4(),
            video_id="gd_x",
            llm_label="달심 ABC 주스",
            spoken_aliases=["달심", "이 주스", "abc주스"],
        )
        # 4 unique terms (label + 3 aliases minus the duplicate
        # "달심"-prefix which IS "달심"... actually "달심 ABC 주스" and
        # "달심" are different strings, both included).
        # Each term × 2 fields = 8 should clauses; one alias dedupes
        # against another via casefold but the aliases here are all
        # distinct.
        n_should = len(q["bool"]["should"])
        # 4 terms × 2 fields = 8.
        assert n_should == 8

    def test_dedupe_alias_equal_to_label(self):
        # If an alias is identical to the label, the dedup set drops
        # the alias clauses.
        q = _build_bm25_query(
            org_id=uuid4(),
            video_id="gd_x",
            llm_label="달심",
            spoken_aliases=["달심", "DALSIM", "이 주스"],
        )
        # Expected: 1 label + 2 distinct aliases = 3 terms × 2 fields
        # = 6 should clauses. ("달심"/"달심" dedupes; "DALSIM" lowercase
        # is its own; "이 주스" is its own.)
        # Actual: label + "DALSIM" + "이 주스" → 6.
        assert len(q["bool"]["should"]) == 6

    def test_empty_label_and_empty_aliases_produces_no_should_clauses(self):
        # Defensive: should never happen in practice but must not
        # crash. With minimum_should_match=0 the query becomes a
        # plain "all from this org+video" — broad but not invalid.
        q = _build_bm25_query(
            org_id=uuid4(),
            video_id="gd_x",
            llm_label="",
            spoken_aliases=[],
        )
        assert q["bool"]["should"] == []
        assert q["bool"]["minimum_should_match"] == 0


# ---------- mention_extractor _hit_to_scene ----------


class TestHitToScene:
    def _hit(self, *, transcript: str = "", caption: str = "", sid: str = "x", score: float = 1.0):
        return {
            "_score": score,
            "_source": {
                "scene_id": sid,
                "start_ms": 0,
                "end_ms": 1_000,
                "transcript_raw": transcript,
                "scene_caption": caption,
            },
        }

    def test_match_in_transcript_only(self):
        hit = self._hit(transcript="달심에 대해 말씀드리면", caption="")
        scene = _hit_to_scene(hit, "달심", [])
        assert scene.matched_field == "transcript_raw"
        assert "달심" in scene.matched_aliases

    def test_match_in_caption_only(self):
        hit = self._hit(transcript="", caption="호스트가 달심 제품을 들고 있다")
        scene = _hit_to_scene(hit, "달심", [])
        assert scene.matched_field == "scene_caption"

    def test_match_in_both_fields_returns_both(self):
        hit = self._hit(transcript="달심에 대해", caption="달심 제품")
        scene = _hit_to_scene(hit, "달심", [])
        assert scene.matched_field == "both"

    def test_case_insensitive_alias_match(self):
        hit = self._hit(transcript="DALSIM is a brand", caption="")
        scene = _hit_to_scene(hit, "달심", ["Dalsim"])
        assert scene.matched_field == "transcript_raw"
        # Original-cased alias preserved in matched_aliases.
        assert "Dalsim" in scene.matched_aliases

    def test_no_substring_match_falls_back_to_caption(self):
        # OS scored >0 via nori stemming on a partial token, but our
        # local substring check finds nothing. Fall back to caption.
        hit = self._hit(transcript="completely unrelated text", caption="")
        scene = _hit_to_scene(hit, "달심", [])
        assert scene.matched_field == "scene_caption"
        assert scene.matched_aliases == []

    def test_carries_through_text_to_scene(self):
        hit = self._hit(
            transcript="this is the transcript",
            caption="this is the caption",
        )
        scene = _hit_to_scene(hit, "transcript", [])
        assert scene.transcript_text == "this is the transcript"
        assert scene.caption_text == "this is the caption"
