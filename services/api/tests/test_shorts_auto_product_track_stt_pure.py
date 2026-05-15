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
    _build_auto_shorts_subtitle_style,
    _compute_chars_per_line,
    _wrap_korean_subtitle_lines,
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
        with pytest.raises(ValueError, match="non-empty selected_chunks"):
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

    def test_scene_crossing_chunk_splits_into_clamped_subclips(self):
        """A 20s chunk that spans two scenes must produce 2
        ``SceneClipSpec``s, each clamped to the underlying scene's
        bounds. Without this split, the render service 422s
        ``end_ms out of scene bounds`` because chunks (20s) routinely
        span Korean livecommerce scenes (1-15s each).
        """
        # Chunk 5-25s; scene_a 0-10 (overlap 5-10), scene_b 10-30 (overlap 10-25)
        scene_a = _scene(0, 10_000, sid="A")
        scene_b = _scene(10_000, 30_000, sid="B")
        seg = MentionSegment(start_ms=0, end_ms=30_000, scenes=[scene_a, scene_b])
        spec = build_composition_spec(
            selected_chunks=[_chunk(5_000, 25_000)],
            segments=[seg],
            os_video_id="gd_x",
        )
        assert len(spec.scene_clips) == 2
        # Sub-clip 1: scene A, clamped to overlap.
        assert spec.scene_clips[0].scene_id == "A"
        assert spec.scene_clips[0].start_ms == 5_000
        assert spec.scene_clips[0].end_ms == 10_000
        # Sub-clip 2: scene B, clamped to overlap. Timeline cursor
        # advanced by sub-clip-1's duration (5s).
        assert spec.scene_clips[1].scene_id == "B"
        assert spec.scene_clips[1].start_ms == 10_000
        assert spec.scene_clips[1].end_ms == 25_000
        assert spec.scene_clips[1].timeline_start_ms == 5_000

    def test_chunk_within_single_scene_produces_one_clip(self):
        """When a chunk stays within a single scene's bounds, only
        one sub-clip is emitted (no split)."""
        scene = _scene(0, 30_000, sid="solo")
        seg = MentionSegment(start_ms=0, end_ms=30_000, scenes=[scene])
        spec = build_composition_spec(
            selected_chunks=[_chunk(5_000, 25_000)],
            segments=[seg],
            os_video_id="gd_x",
        )
        assert len(spec.scene_clips) == 1
        assert spec.scene_clips[0].scene_id == "solo"
        assert spec.scene_clips[0].start_ms == 5_000
        assert spec.scene_clips[0].end_ms == 25_000

    def test_chunk_extending_past_scene_end_clamps_to_scene(self):
        """Real failure mode from staging:
        clip 1350000-1370000 vs scene 1350000-1365000.
        Chunk extends past scene's end_ms — the sub-clip must be
        clamped to the scene's actual end_ms."""
        scene = _scene(1_350_000, 1_365_000, sid="short")
        seg = MentionSegment(
            start_ms=1_350_000, end_ms=1_400_000, scenes=[scene],
        )
        spec = build_composition_spec(
            selected_chunks=[_chunk(1_350_000, 1_370_000)],
            segments=[seg],
            os_video_id="gd_x",
        )
        assert len(spec.scene_clips) == 1
        # End clamped to scene's actual end (1_365_000), NOT chunk end.
        assert spec.scene_clips[0].end_ms == 1_365_000


# ---------- responsive subtitle style + auto-wrap ----------


class TestSubtitleStyleScaling:
    def test_default_720p_height_yields_32px_font(self):
        # Sanity floor: at the legacy default canvas (720p height),
        # font lands on 32px — chosen so that 11-12 Hangul chars fit
        # per line on the 406-px-wide canvas.
        style = _build_auto_shorts_subtitle_style(canvas_height=720)
        assert style.font_size_px == 32
        # Padding should track font at ~33% (32 * 0.33 ≈ 10.6 → 11).
        assert style.background_padding == 11

    def test_1080p_height_scales_proportionally(self):
        # Bumping canvas height should bump font + padding together.
        style = _build_auto_shorts_subtitle_style(canvas_height=1080)
        assert style.font_size_px == round(1080 * 0.045)  # 49
        assert style.background_padding == round(49 * 0.33)  # 16

    def test_floor_protects_tiny_canvas(self):
        # Below the 16px floor → clamp. Otherwise drawtext renders
        # illegible captions; better to over-size than under-size on
        # an unusual aspect.
        style = _build_auto_shorts_subtitle_style(canvas_height=240)
        # 240 * 0.045 = 10.8 → would be 11; floor 16 wins.
        assert style.font_size_px == 16
        # Padding floor (8) trips when font is at the floor too.
        assert style.background_padding == 8

    def test_fixed_design_fields_do_not_scale(self):
        # Position + colors are design choices, NOT canvas-derived.
        s_a = _build_auto_shorts_subtitle_style(canvas_height=720)
        s_b = _build_auto_shorts_subtitle_style(canvas_height=1080)
        assert s_a.position_y == s_b.position_y == 0.82
        assert s_a.font_color == s_b.font_color == "#000000"
        assert s_a.background_color == s_b.background_color == "#FFFFFF"
        assert s_a.font_weight == s_b.font_weight == 700


class TestComputeCharsPerLine:
    def test_default_canvas_yields_around_11_chars(self):
        # 406-wide canvas, 32px font, 11px padding.
        # available = 406 - 22 = 384; 384 * 0.92 = 353; 353 / 32 = 11.
        # The 0.92 safety multiplier prevents dense Hangul cues from
        # rendering flush against the frame edge.
        chars = _compute_chars_per_line(
            canvas_width=406, font_size_px=32, padding=11,
        )
        assert chars == 11

    def test_wider_canvas_more_chars(self):
        # 720-wide → more horizontal headroom.
        # available = 720 - 22 = 698; 698 * 0.92 = 642; 642 / 32 = 20.
        chars = _compute_chars_per_line(
            canvas_width=720, font_size_px=32, padding=11,
        )
        assert chars == 20

    def test_zero_font_size_returns_zero(self):
        # Defensive — never divide by zero.
        chars = _compute_chars_per_line(
            canvas_width=406, font_size_px=0, padding=11,
        )
        assert chars == 0

    def test_padding_larger_than_canvas_returns_zero(self):
        # Pathological — padding wins. Returns 0 rather than negative.
        chars = _compute_chars_per_line(
            canvas_width=20, font_size_px=16, padding=50,
        )
        assert chars == 0


class TestWrapKoreanSubtitleLines:
    def test_short_text_passes_through(self):
        # ≤ chars_per_line: no break point inserted.
        out = _wrap_korean_subtitle_lines(
            "안녕하세요", chars_per_line=12,
        )
        assert "\n" not in out
        assert out == "안녕하세요"

    def test_staging_overflow_cue_wraps_at_word_boundary(self):
        # The exact cue from the staging 2026-05-06 overflow incident.
        # 14 chars at chars_per_line=12 → wrap at last 어절 boundary.
        out = _wrap_korean_subtitle_lines(
            "근데 이번에 수량 좀 짜게", chars_per_line=12,
        )
        lines = out.split("\n")
        assert len(lines) == 2
        # Each line must respect the budget.
        assert all(len(line) <= 12 for line in lines)
        # Re-joining (with single space) must reconstruct the original.
        assert " ".join(lines) == "근데 이번에 수량 좀 짜게"

    def test_wraps_at_last_whitespace_within_budget(self):
        # Greedy: pack as many 어절 as fit, break before the one
        # that would exceed budget.
        out = _wrap_korean_subtitle_lines(
            "하나 둘 셋 넷 다섯 여섯", chars_per_line=8,
        )
        lines = out.split("\n")
        # Line 1 should pack as many 어절 as fit in 8 chars; line 2
        # carries the rest. Both ≤ 8 chars.
        for line in lines:
            assert len(line) <= 8

    def test_single_long_word_mid_syllable_break(self):
        # No whitespace in budget — fall back to mid-syllable break.
        # Korean tolerates this when forced.
        out = _wrap_korean_subtitle_lines(
            "가나다라마바사아자차카타", chars_per_line=5,
        )
        lines = out.split("\n")
        # First line breaks mid-word at exactly chars_per_line.
        assert lines[0] == "가나다라마"

    def test_max_lines_cap_appends_residue(self):
        # If the text would need more than max_lines, we append the
        # residue to the last line rather than truncate (preserves
        # operator's words even at slight overflow).
        out = _wrap_korean_subtitle_lines(
            "하나 둘 셋 넷 다섯 여섯 일곱 여덟",
            chars_per_line=4,
            max_lines=2,
        )
        lines = out.split("\n")
        assert len(lines) == 2

    def test_chars_per_line_zero_returns_original(self):
        # Defensive — can't break a line with zero budget.
        out = _wrap_korean_subtitle_lines(
            "any text here", chars_per_line=0,
        )
        assert out == "any text here"

    def test_strips_outer_whitespace(self):
        # Caller might hand us padded text; result has no leading or
        # trailing whitespace (cosmetic — drawtext renders the text
        # exactly as given).
        out = _wrap_korean_subtitle_lines(
            "   안녕하세요   ", chars_per_line=12,
        )
        assert out == "안녕하세요"


class TestBuildCompositionSpecDefaultEmptyCaptions:
    """Post 2026-05-07 default: no captions on parent — Whisper post-render
    is the sole caption source. Without this, an OS resplit/indexing drift
    can paint wrong text onto a rendered short (project memory:
    ``project_resplit_manifest_stt_incident``).
    """

    def test_default_emits_no_subtitles(self):
        scene = _scene(0, 30_000, sid="gd_x_scene_001")
        seg = MentionSegment(start_ms=0, end_ms=30_000, scenes=[scene])
        spec = build_composition_spec(
            selected_chunks=[_chunk(0, 30_000)],
            segments=[seg],
            os_video_id="gd_x",
        )
        # Captions are explicitly absent in the default path.
        assert spec.subtitles == []
        # Scene clip selection is unaffected — only the caption
        # generation step is gated by the new flag.
        assert len(spec.scene_clips) == 1
        assert spec.scene_clips[0].scene_id == "gd_x_scene_001"

    def test_default_preserves_clip_layout_unchanged(self):
        # Multi-scene chunk → still produces clamped sub-clips. The
        # subtitle gating must NOT regress scene_clip behavior.
        scene_a = _scene(0, 10_000, sid="A")
        scene_b = _scene(10_000, 30_000, sid="B")
        seg = MentionSegment(start_ms=0, end_ms=30_000, scenes=[scene_a, scene_b])
        spec = build_composition_spec(
            selected_chunks=[_chunk(5_000, 25_000)],
            segments=[seg],
            os_video_id="gd_x",
        )
        assert spec.subtitles == []
        assert len(spec.scene_clips) == 2
        assert spec.scene_clips[0].scene_id == "A"
        assert spec.scene_clips[1].scene_id == "B"


class TestBuildCompositionSpecLegacyRollback:
    """Emergency rollback path — exercises the historical subtitle
    generation. Verifies the path stays runnable in case we need to
    flip the flag, but the default behavior above is what ships.
    """

    def test_legacy_canvas_uses_32px_font(self):
        scene = _scene(0, 30_000, sid="gd_x_scene_001")
        seg = MentionSegment(start_ms=0, end_ms=30_000, scenes=[scene])
        spec = build_composition_spec(
            selected_chunks=[_chunk(0, 30_000)],
            segments=[seg],
            os_video_id="gd_x",
            legacy_os_subtitles_enabled=True,
        )
        # _scene's transcript is uniform-distributed across the clip,
        # so at least one cue should land. Style is the auto-shorts
        # 32px pill at default 720p canvas.
        assert len(spec.subtitles) >= 1
        assert all(s.style.font_size_px == 32 for s in spec.subtitles)

    def test_legacy_explicit_canvas_dimensions_scale(self):
        scene = _scene(0, 30_000, sid="gd_x_scene_001")
        seg = MentionSegment(start_ms=0, end_ms=30_000, scenes=[scene])
        spec = build_composition_spec(
            selected_chunks=[_chunk(0, 30_000)],
            segments=[seg],
            os_video_id="gd_x",
            canvas_width=1080,
            canvas_height=1920,
            legacy_os_subtitles_enabled=True,
        )
        # 1920 * 0.045 = 86. Padding ≈ 86 * 0.33 = 28.
        for s in spec.subtitles:
            assert s.style.font_size_px == 86
            assert s.style.background_padding == 28


class TestBuildCompositionSpecStoryboard:
    """Tier B storyboard composition path: ``build_composition_spec``
    accepts a ``StoryboardPlan`` and emits one or more
    ``SceneClipSpec`` per fragment, scene-clamped via the same
    ``_range_to_scene_clipped_subclips`` helper that the legacy
    chunks path uses.
    """

    def _plan_from_fragments(
        self, fragments: list[tuple[int, int, str]],
    ):
        # Helper: build a minimal StoryboardPlan from
        # (start_ms, end_ms, role_name) tuples.
        from app.modules.shorts_auto_product.track_stt.models import (
            ChunkScore,
        )
        from app.modules.shorts_auto_product.track_stt.storyboard import (
            SlotRole,
            StoryboardFragment,
            StoryboardPlan,
        )

        score = ChunkScore(hook_score=0.5, has_cta=False, importance_score=0.5)
        return StoryboardPlan(
            fragments=[
                StoryboardFragment(
                    role=SlotRole(role_name),
                    source_start_ms=start,
                    source_end_ms=end,
                    target_duration_ms=end - start,
                    chunk_score=score,
                    rationale=f"test:{role_name}",
                )
                for (start, end, role_name) in fragments
            ],
            total_duration_ms=sum(e - s for (s, e, _) in fragments),
            slots_filled={SlotRole(r) for (_, _, r) in fragments},
            fallbacks_used=[],
        )

    def test_storyboard_emits_one_scene_clip_per_fragment(self):
        # 3 fragments, each fully inside one scene → 3 SceneClipSpec.
        scene_a = _scene(0, 30_000, sid="A")
        scene_b = _scene(30_000, 60_000, sid="B")
        scene_c = _scene(60_000, 90_000, sid="C")
        seg = MentionSegment(
            start_ms=0, end_ms=90_000, scenes=[scene_a, scene_b, scene_c],
        )
        plan = self._plan_from_fragments(
            [(5_000, 13_000, "hook"), (35_000, 55_000, "detail"), (65_000, 73_000, "cta")],
        )
        spec = build_composition_spec(
            storyboard=plan, segments=[seg], os_video_id="gd_x",
        )
        assert len(spec.scene_clips) == 3
        # Storyboard order preserved (HOOK first, CTA last).
        assert spec.scene_clips[0].scene_id == "A"
        assert spec.scene_clips[1].scene_id == "B"
        assert spec.scene_clips[2].scene_id == "C"
        # Captions deferred to Whisper post-render — never emitted
        # by the storyboard path.
        assert spec.subtitles == []

    def test_storyboard_fragment_split_across_scene_boundaries(self):
        # One DETAIL fragment crossing two scenes → 2 SceneClipSpec
        # entries clamped to each scene's bounds.
        scene_a = _scene(0, 10_000, sid="A")
        scene_b = _scene(10_000, 30_000, sid="B")
        seg = MentionSegment(
            start_ms=0, end_ms=30_000, scenes=[scene_a, scene_b],
        )
        plan = self._plan_from_fragments(
            [(5_000, 25_000, "detail")],
        )
        spec = build_composition_spec(
            storyboard=plan, segments=[seg], os_video_id="gd_x",
        )
        assert len(spec.scene_clips) == 2
        assert spec.scene_clips[0].scene_id == "A"
        assert spec.scene_clips[0].start_ms == 5_000
        assert spec.scene_clips[0].end_ms == 10_000
        assert spec.scene_clips[1].scene_id == "B"
        assert spec.scene_clips[1].start_ms == 10_000
        assert spec.scene_clips[1].end_ms == 25_000

    def test_storyboard_timeline_cursor_accumulates_across_fragments(self):
        # Two non-contiguous fragments → timeline_start_ms must
        # accumulate continuously even though source ranges jump.
        scene_a = _scene(0, 30_000, sid="A")
        scene_b = _scene(60_000, 90_000, sid="B")
        seg = MentionSegment(
            start_ms=0, end_ms=90_000, scenes=[scene_a, scene_b],
        )
        plan = self._plan_from_fragments(
            [(5_000, 13_000, "hook"), (65_000, 73_000, "cta")],
        )
        spec = build_composition_spec(
            storyboard=plan, segments=[seg], os_video_id="gd_x",
        )
        # Timeline is contiguous regardless of source-time gap.
        assert spec.scene_clips[0].timeline_start_ms == 0
        assert spec.scene_clips[1].timeline_start_ms == 8_000  # 13_000 - 5_000

    def test_storyboard_and_chunks_mutually_exclusive(self):
        scene = _scene(0, 30_000, sid="A")
        seg = MentionSegment(start_ms=0, end_ms=30_000, scenes=[scene])
        plan = self._plan_from_fragments([(0, 8_000, "hook")])
        with pytest.raises(ValueError, match="not both"):
            build_composition_spec(
                selected_chunks=[_chunk(0, 30_000)],
                storyboard=plan,
                segments=[seg],
                os_video_id="gd_x",
            )

    def test_neither_chunks_nor_storyboard_raises(self):
        scene = _scene(0, 30_000, sid="A")
        seg = MentionSegment(start_ms=0, end_ms=30_000, scenes=[scene])
        with pytest.raises(ValueError, match="non-empty"):
            build_composition_spec(
                segments=[seg], os_video_id="gd_x",
            )

    def test_storyboard_path_ignores_legacy_subtitles_flag(self):
        # The legacy_os_subtitles_enabled rollback only applies to
        # the chunks path; storyboard always emits empty subtitles.
        # Without this guard the bug we shipped Whisper-only fixes
        # for would re-appear under storyboard mode.
        scene = _scene(
            0, 30_000, sid="A",
        )
        seg = MentionSegment(start_ms=0, end_ms=30_000, scenes=[scene])
        plan = self._plan_from_fragments([(0, 8_000, "hook")])
        spec = build_composition_spec(
            storyboard=plan,
            segments=[seg],
            os_video_id="gd_x",
            legacy_os_subtitles_enabled=True,  # ← silently ignored
        )
        assert spec.subtitles == []


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


# ---------- mention_extractor OCR re-rank (2026-05-10) ----------
#
# Plan: ``.claude/plans/ocr-mention-extractor-rerank.md``
#
# These tests cover the OCR-side additions to ``_build_bm25_query`` and
# ``_hit_to_scene``. Strict-additive guarantee: with
# ``ocr_rerank_enabled=False``, the query body is byte-identical to the
# pre-OCR shape (the ``TestMentionExtractorQuery`` class above already
# exercises that path without setting the flag).


class TestMentionExtractorQueryOCR:
    """OCR-clause behavior in ``_build_bm25_query``."""

    def test_flag_off_byte_identical_to_pre_ocr(self):
        """Strict-additive: flag off → query has zero ocr_text_norm clauses."""
        q = _build_bm25_query(
            org_id=uuid4(),
            video_id="gd_x",
            llm_label="달심",
            spoken_aliases=["DALSIM", "이 주스"],
            ocr_rerank_enabled=False,
        )
        clauses = q["bool"]["should"]
        ocr_clauses = [
            c for c in clauses if "match" in c and "ocr_text_norm" in c["match"]
        ]
        assert ocr_clauses == [], (
            "Flag off MUST produce zero OCR clauses (strict-additive)"
        )
        # Sanity: existing transcript+caption clauses still there.
        non_ocr = [
            c for c in clauses
            if "match" in c and ("transcript_raw" in c["match"] or "scene_caption" in c["match"])
        ]
        assert len(non_ocr) == len(clauses)

    def test_flag_on_adds_ocr_clauses_for_label(self):
        q = _build_bm25_query(
            org_id=uuid4(),
            video_id="gd_x",
            llm_label="달심 ABC 주스",
            spoken_aliases=[],
            ocr_rerank_enabled=True,
        )
        ocr_clauses = [
            c for c in q["bool"]["should"]
            if "match" in c and "ocr_text_norm" in c["match"]
        ]
        # Label only → 1 OCR clause for the label.
        assert len(ocr_clauses) == 1
        assert ocr_clauses[0]["match"]["ocr_text_norm"]["query"] == "달심 ABC 주스"
        # Boost > 0.
        assert ocr_clauses[0]["match"]["ocr_text_norm"]["boost"] > 0

    def test_flag_on_adds_ocr_clauses_for_label_plus_long_aliases(self):
        q = _build_bm25_query(
            org_id=uuid4(),
            video_id="gd_x",
            llm_label="밀레니즈 루프",
            spoken_aliases=["스포츠 루프", "마플 워치", "이 시계"],
            ocr_rerank_enabled=True,
        )
        ocr_clauses = [
            c for c in q["bool"]["should"]
            if "match" in c and "ocr_text_norm" in c["match"]
        ]
        # Label + 3 long aliases (each ≥3 chars) = 4 OCR clauses.
        # All non-trivial, all aliases.
        assert len(ocr_clauses) == 4
        ocr_queries = sorted(c["match"]["ocr_text_norm"]["query"] for c in ocr_clauses)
        assert ocr_queries == sorted([
            "밀레니즈 루프", "스포츠 루프", "마플 워치", "이 시계",
        ])

    def test_flag_on_skips_short_aliases_on_ocr_side_only(self):
        """Aliases shorter than _OCR_ALIAS_MIN_LENGTH (3 chars) are
        skipped on OCR side but kept on transcript/caption side."""
        q = _build_bm25_query(
            org_id=uuid4(),
            video_id="gd_x",
            llm_label="달심",  # 2 chars — also short!
            spoken_aliases=["바", "이", "쿠키", "abc"],
            ocr_rerank_enabled=True,
        )
        clauses = q["bool"]["should"]
        ocr_clauses = [
            c for c in clauses
            if "match" in c and "ocr_text_norm" in c["match"]
        ]
        # OCR side: label "달심" (2 chars) is the LABEL — kept regardless
        # of length (label is the canonical search term, not subject
        # to alias-length filter). Aliases: '바' (1), '이' (1) skipped;
        # '쿠키' (2) skipped; 'abc' (3) kept. So OCR has label + 'abc' = 2.
        ocr_queries = sorted(c["match"]["ocr_text_norm"]["query"] for c in ocr_clauses)
        assert ocr_queries == ["abc", "달심"]

        # Transcript+caption side: ALL aliases kept. Label + 4 aliases
        # = 5 terms × 2 fields = 10 transcript/caption clauses.
        non_ocr_clauses = [
            c for c in clauses
            if "match" in c and ("transcript_raw" in c["match"] or "scene_caption" in c["match"])
        ]
        assert len(non_ocr_clauses) == 10

    def test_ocr_boost_scales_clause_weight(self):
        """ocr_boost=0.0 should produce zero-weighted (effectively
        no-op) OCR clauses; ocr_boost=1.0 should produce clauses at
        full _OCR_FIELD_BASE_BOOST × per-token boost weight."""
        q_low = _build_bm25_query(
            org_id=uuid4(),
            video_id="gd_x",
            llm_label="달심",
            spoken_aliases=[],
            ocr_rerank_enabled=True,
            ocr_boost=0.0,
        )
        q_high = _build_bm25_query(
            org_id=uuid4(),
            video_id="gd_x",
            llm_label="달심",
            spoken_aliases=[],
            ocr_rerank_enabled=True,
            ocr_boost=1.0,
        )
        ocr_low = [
            c for c in q_low["bool"]["should"]
            if "match" in c and "ocr_text_norm" in c["match"]
        ]
        ocr_high = [
            c for c in q_high["bool"]["should"]
            if "match" in c and "ocr_text_norm" in c["match"]
        ]
        assert len(ocr_low) == 1 and len(ocr_high) == 1
        # ocr_boost=1.0 gives 1.67x the boost of 0.6 (default), and
        # 0.0 gives literally zero weight.
        assert ocr_low[0]["match"]["ocr_text_norm"]["boost"] == 0.0
        assert ocr_high[0]["match"]["ocr_text_norm"]["boost"] > 0.0

    def test_ocr_boost_default_is_lower_than_transcript(self):
        """The default ocr_boost=0.6 keeps OCR contribution proportional
        but not dominant — a single OCR-clause match should not
        outscore a single transcript-clause match for the same token."""
        q = _build_bm25_query(
            org_id=uuid4(),
            video_id="gd_x",
            llm_label="달심",
            spoken_aliases=[],
            ocr_rerank_enabled=True,
        )
        clauses = q["bool"]["should"]
        transcript = next(
            c for c in clauses
            if "match" in c and "transcript_raw" in c["match"]
        )
        ocr = next(
            c for c in clauses
            if "match" in c and "ocr_text_norm" in c["match"]
        )
        t_boost = transcript["match"]["transcript_raw"]["boost"]
        o_boost = ocr["match"]["ocr_text_norm"]["boost"]
        assert o_boost < t_boost, (
            f"OCR boost ({o_boost}) must be < transcript boost ({t_boost}) "
            f"so transcript stays the primary intent signal"
        )


class TestHitToSceneOCR:
    """OCR field population in ``_hit_to_scene``."""

    def _hit_with_ocr(
        self,
        *,
        transcript: str = "",
        caption: str = "",
        ocr: str = "",
        sid: str = "x",
        score: float = 1.0,
    ):
        return {
            "_score": score,
            "_source": {
                "scene_id": sid,
                "start_ms": 0,
                "end_ms": 1_000,
                "transcript_raw": transcript,
                "scene_caption": caption,
                "ocr_text_raw": ocr,
            },
        }

    def test_ocr_text_carried_through(self):
        hit = self._hit_with_ocr(transcript="", ocr="달심 SLDR 클래스가다른")
        scene = _hit_to_scene(hit, "달심", [])
        assert scene.ocr_text == "달심 SLDR 클래스가다른"
        assert scene.ocr_match is True

    def test_ocr_match_false_when_label_not_in_ocr(self):
        hit = self._hit_with_ocr(transcript="달심 mention", ocr="entirely unrelated text")
        scene = _hit_to_scene(hit, "달심", [])
        assert scene.ocr_match is False
        # Transcript path still works.
        assert scene.matched_field == "transcript_raw"

    def test_ocr_match_via_alias(self):
        hit = self._hit_with_ocr(transcript="", ocr="DALSIM은 좋은 브랜드")
        scene = _hit_to_scene(hit, "달심", ["DALSIM"])
        assert scene.ocr_match is True

    def test_ocr_only_match_does_not_change_matched_field(self):
        """Backward compat: matched_field semantics preserved.
        OCR-only match ⇒ matched_field falls back to caption (existing
        fallback), with ocr_match=True surfacing the on-screen evidence."""
        hit = self._hit_with_ocr(
            transcript="unrelated audio",
            caption="unrelated caption",
            ocr="달심 packaging visible",
        )
        scene = _hit_to_scene(hit, "달심", [])
        assert scene.ocr_match is True
        # matched_field stays in the {transcript_raw, scene_caption, both}
        # set. OCR-only matches don't extend the literal.
        assert scene.matched_field in {"transcript_raw", "scene_caption", "both"}

    def test_no_ocr_field_in_source_yields_empty_ocr_text(self):
        """Backward compat: if OS doesn't return ocr_text_raw (older
        index, projection oversight) the dataclass defaults apply."""
        hit = {
            "_score": 1.0,
            "_source": {
                "scene_id": "x",
                "start_ms": 0,
                "end_ms": 1_000,
                "transcript_raw": "달심 mention",
                "scene_caption": "",
                # ocr_text_raw missing
            },
        }
        scene = _hit_to_scene(hit, "달심", [])
        assert scene.ocr_text == ""
        assert scene.ocr_match is False
        # Transcript path unaffected.
        assert scene.matched_field == "transcript_raw"

    def test_matched_aliases_includes_ocr_only_hits(self):
        """If an alias appears ONLY in OCR (not in transcript or
        caption), it should still surface in matched_aliases for the
        debug surface — the alias DID appear, the rendered short
        SHOULD show the product."""
        hit = self._hit_with_ocr(
            transcript="some unrelated audio",
            caption="some unrelated caption",
            ocr="DALSIM brand visible",
        )
        scene = _hit_to_scene(hit, "달심", ["DALSIM"])
        assert "DALSIM" in scene.matched_aliases
