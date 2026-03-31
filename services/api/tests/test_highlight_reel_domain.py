"""Unit tests for highlight reel domain algorithm.

All tests are pure — no mocking, no I/O, no framework dependencies.
Tests the Max-Diversity Run Sampler algorithm in isolation.
"""
import pytest

from app.modules.highlight_reel.domain import (
    HighlightPlan,
    HighlightRequest,
    Run,
    SceneRecord,
    SelectedClip,
    _detect_runs,
    _distribute_budget,
    _filter_excluded,
    _group_by_video,
    _order_and_assign_timeline,
    _score_run,
    _select_clips,
    _trim_run,
    build_highlight_plan,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scene(scene_id: str, video_id: str, start_ms: int, end_ms: int) -> SceneRecord:
    return SceneRecord(scene_id=scene_id, video_id=video_id, start_ms=start_ms, end_ms=end_ms)


def _consecutive_scenes(video_id: str, count: int, duration_ms: int = 45000, start_offset: int = 0) -> list[SceneRecord]:
    """Generate count consecutive scenes of given duration."""
    scenes = []
    cursor = start_offset
    for i in range(count):
        scenes.append(_scene(f"{video_id}_s{i}", video_id, cursor, cursor + duration_ms))
        cursor += duration_ms
    return scenes


def _request(target_s: int = 120, excluded: set[str] | None = None) -> HighlightRequest:
    return HighlightRequest(
        target_duration_ms=target_s * 1000,
        excluded_video_ids=frozenset(excluded or set()),
    )


# ---------------------------------------------------------------------------
# Run Detection
# ---------------------------------------------------------------------------

class TestDetectRuns:
    def test_consecutive_scenes_form_single_run(self):
        scenes = _consecutive_scenes("v1", 3, duration_ms=45000)
        runs = _detect_runs(scenes)
        assert len(runs) == 1
        assert runs[0].scene_count == 3
        assert runs[0].duration_ms == 135000
        assert runs[0].start_ms == 0
        assert runs[0].end_ms == 135000

    def test_gap_creates_separate_runs(self):
        scenes = [
            _scene("s1", "v1", 0, 45000),
            _scene("s2", "v1", 45000, 90000),
            # gap here
            _scene("s3", "v1", 200000, 245000),
        ]
        runs = _detect_runs(scenes)
        assert len(runs) == 2
        assert runs[0].scene_count == 2
        assert runs[0].duration_ms == 90000
        assert runs[1].scene_count == 1
        assert runs[1].duration_ms == 45000

    def test_single_scene_is_a_run(self):
        scenes = [_scene("s1", "v1", 100000, 145000)]
        runs = _detect_runs(scenes)
        assert len(runs) == 1
        assert runs[0].scene_count == 1

    def test_empty_input(self):
        assert _detect_runs([]) == []

    def test_all_isolated_scenes(self):
        scenes = [
            _scene("s1", "v1", 0, 5000),
            _scene("s2", "v1", 10000, 15000),
            _scene("s3", "v1", 20000, 25000),
        ]
        runs = _detect_runs(scenes)
        assert len(runs) == 3
        assert all(r.scene_count == 1 for r in runs)

    def test_first_scene_id_is_preserved(self):
        scenes = _consecutive_scenes("v1", 4)
        runs = _detect_runs(scenes)
        assert runs[0].first_scene_id == "v1_s0"

    def test_multiple_runs_with_varying_lengths(self):
        scenes = [
            *_consecutive_scenes("v1", 2, start_offset=0),        # run of 2
            *_consecutive_scenes("v1", 1, start_offset=200000),    # run of 1
            *_consecutive_scenes("v1", 5, start_offset=400000),    # run of 5
        ]
        scenes.sort(key=lambda s: s.start_ms)
        runs = _detect_runs(scenes)
        assert len(runs) == 3
        assert [r.scene_count for r in runs] == [2, 1, 5]


# ---------------------------------------------------------------------------
# Filter Excluded
# ---------------------------------------------------------------------------

class TestFilterExcluded:
    def test_no_exclusions_returns_all(self):
        scenes = _consecutive_scenes("v1", 3)
        result = _filter_excluded(scenes, frozenset())
        assert len(result) == 3

    def test_excludes_matching_videos(self):
        scenes = [
            _scene("s1", "v1", 0, 5000),
            _scene("s2", "v2", 0, 5000),
            _scene("s3", "v3", 0, 5000),
        ]
        result = _filter_excluded(scenes, frozenset({"v2"}))
        assert len(result) == 2
        assert all(s.video_id != "v2" for s in result)

    def test_exclude_all_videos(self):
        scenes = [_scene("s1", "v1", 0, 5000), _scene("s2", "v2", 0, 5000)]
        result = _filter_excluded(scenes, frozenset({"v1", "v2"}))
        assert result == []


# ---------------------------------------------------------------------------
# Group By Video
# ---------------------------------------------------------------------------

class TestGroupByVideo:
    def test_groups_correctly(self):
        scenes = [
            _scene("s1", "v1", 0, 5000),
            _scene("s2", "v2", 0, 5000),
            _scene("s3", "v1", 5000, 10000),
        ]
        groups = _group_by_video(scenes)
        assert len(groups) == 2
        assert len(groups["v1"]) == 2
        assert len(groups["v2"]) == 1

    def test_sorts_by_start_ms(self):
        scenes = [
            _scene("s2", "v1", 90000, 135000),
            _scene("s1", "v1", 0, 45000),
            _scene("s3", "v1", 45000, 90000),
        ]
        groups = _group_by_video(scenes)
        start_times = [s.start_ms for s in groups["v1"]]
        assert start_times == [0, 45000, 90000]


# ---------------------------------------------------------------------------
# Budget Distribution
# ---------------------------------------------------------------------------

class TestDistributeBudget:
    def test_even_split(self):
        vids = ["v1", "v2", "v3"]
        selected, budget = _distribute_budget(vids, 120000)
        assert len(selected) == 3
        assert budget == 40000

    def test_caps_videos_when_too_many(self):
        vids = [f"v{i}" for i in range(20)]
        selected, budget = _distribute_budget(vids, 30000)
        # 30s / 10s min = 3 videos max
        assert len(selected) == 3
        assert budget == 10000

    def test_single_video_gets_full_budget(self):
        selected, budget = _distribute_budget(["v1"], 120000)
        assert len(selected) == 1
        assert budget == 120000

    def test_empty_videos(self):
        selected, budget = _distribute_budget([], 120000)
        assert selected == []
        assert budget == 0

    def test_two_videos_60s(self):
        selected, budget = _distribute_budget(["v1", "v2"], 60000)
        assert len(selected) == 2
        assert budget == 30000


# ---------------------------------------------------------------------------
# Run Scoring
# ---------------------------------------------------------------------------

class TestScoreRun:
    def test_mid_position_scores_higher(self):
        # Middle run in a video with 5 runs
        mid_score = _score_run(
            Run("v1", 0, 30000, 1, "s1"), budget_ms=30000, run_index=2, total_runs=5,
        )
        edge_score = _score_run(
            Run("v1", 0, 30000, 1, "s1"), budget_ms=30000, run_index=0, total_runs=5,
        )
        assert mid_score > edge_score

    def test_duration_close_to_budget_scores_higher(self):
        # Run duration matches budget perfectly
        perfect = _score_run(
            Run("v1", 0, 30000, 1, "s1"), budget_ms=30000, run_index=1, total_runs=3,
        )
        # Run duration is way off from budget
        mismatched = _score_run(
            Run("v1", 0, 5000, 1, "s1"), budget_ms=30000, run_index=1, total_runs=3,
        )
        assert perfect > mismatched

    def test_multi_scene_run_scores_higher(self):
        single = _score_run(
            Run("v1", 0, 30000, 1, "s1"), budget_ms=30000, run_index=1, total_runs=3,
        )
        multi = _score_run(
            Run("v1", 0, 30000, 4, "s1"), budget_ms=30000, run_index=1, total_runs=3,
        )
        assert multi > single

    def test_score_is_positive(self):
        score = _score_run(
            Run("v1", 0, 10000, 1, "s1"), budget_ms=30000, run_index=0, total_runs=1,
        )
        assert score > 0

    def test_single_run_in_video_gets_max_position(self):
        score = _score_run(
            Run("v1", 0, 30000, 1, "s1"), budget_ms=30000, run_index=0, total_runs=1,
        )
        # position should be 1.0 for single run
        assert score > 0.5


# ---------------------------------------------------------------------------
# Trimming
# ---------------------------------------------------------------------------

class TestTrimRun:
    def test_no_trim_when_fits(self):
        run = Run("v1", 10000, 40000, 1, "s1")  # 30s
        start, end = _trim_run(run, 30000)
        assert start == 10000
        assert end == 40000

    def test_trims_from_middle(self):
        run = Run("v1", 0, 120000, 4, "s1")  # 120s run
        start, end = _trim_run(run, 30000)
        # Should take 30s from the middle: excess=90s, trim_start=45s, trim_end=75s
        assert start == 45000
        assert end == 75000
        assert end - start == 30000

    def test_trim_preserves_exact_budget(self):
        run = Run("v1", 0, 270000, 6, "s1")  # 270s
        start, end = _trim_run(run, 24000)
        assert end - start == 24000

    def test_short_run_not_trimmed(self):
        run = Run("v1", 50000, 55000, 1, "s1")  # 5s
        start, end = _trim_run(run, 30000)
        assert start == 50000
        assert end == 55000


# ---------------------------------------------------------------------------
# Clip Selection
# ---------------------------------------------------------------------------

class TestSelectClips:
    def test_selects_one_clip_per_video(self):
        runs_by_video = {
            "v1": [Run("v1", 0, 90000, 2, "s1"), Run("v1", 200000, 245000, 1, "s3")],
            "v2": [Run("v2", 0, 135000, 3, "s4")],
        }
        clips = _select_clips(runs_by_video, ["v1", "v2"], 60000, 120000)
        videos_in_clips = {c.video_id for c in clips}
        assert "v1" in videos_in_clips
        assert "v2" in videos_in_clips

    def test_total_does_not_exceed_target(self):
        runs_by_video = {
            f"v{i}": _detect_runs(_consecutive_scenes(f"v{i}", 10))
            for i in range(5)
        }
        clips = _select_clips(runs_by_video, list(runs_by_video.keys()), 24000, 120000)
        total = sum(c.duration_ms for c in clips)
        assert total <= 120000

    def test_respects_per_video_budget(self):
        runs_by_video = {
            "v1": [Run("v1", 0, 500000, 10, "s1")],  # very long
            "v2": [Run("v2", 0, 500000, 10, "s2")],
        }
        clips = _select_clips(runs_by_video, ["v1", "v2"], 60000, 120000)
        for c in clips:
            assert c.duration_ms <= 60000


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------

class TestOrderAndAssignTimeline:
    def test_timeline_positions_are_sequential(self):
        clips = [
            SelectedClip("v1", "s1", 0, 30000),
            SelectedClip("v2", "s2", 0, 30000),
            SelectedClip("v1", "s3", 60000, 90000),
        ]
        runs_by_video = {
            "v1": [Run("v1", 0, 90000, 2, "s1")],
            "v2": [Run("v2", 0, 30000, 1, "s2")],
        }
        ordered = _order_and_assign_timeline(clips, runs_by_video)
        for i in range(1, len(ordered)):
            expected_start = ordered[i - 1].timeline_start_ms + ordered[i - 1].duration_ms
            assert ordered[i].timeline_start_ms == expected_start

    def test_no_overlapping_timeline(self):
        clips = [
            SelectedClip("v1", "s1", 0, 20000),
            SelectedClip("v2", "s2", 5000, 25000),
            SelectedClip("v3", "s3", 10000, 30000),
        ]
        runs_by_video = {
            "v1": [Run("v1", 0, 20000, 1, "s1")],
            "v2": [Run("v2", 5000, 25000, 1, "s2")],
            "v3": [Run("v3", 10000, 30000, 1, "s3")],
        }
        ordered = _order_and_assign_timeline(clips, runs_by_video)
        for i in range(1, len(ordered)):
            prev_end = ordered[i - 1].timeline_start_ms + ordered[i - 1].duration_ms
            assert ordered[i].timeline_start_ms >= prev_end

    def test_empty_clips(self):
        assert _order_and_assign_timeline([], {}) == []

    def test_videos_ordered_by_richness(self):
        clips = [
            SelectedClip("v_small", "s1", 0, 10000),
            SelectedClip("v_big", "s2", 0, 10000),
        ]
        runs_by_video = {
            "v_big": [Run("v_big", 0, 500000, 10, "s2")],      # more content
            "v_small": [Run("v_small", 0, 10000, 1, "s1")],     # less content
        }
        ordered = _order_and_assign_timeline(clips, runs_by_video)
        assert ordered[0].video_id == "v_big"
        assert ordered[1].video_id == "v_small"


# ---------------------------------------------------------------------------
# build_highlight_plan — end-to-end
# ---------------------------------------------------------------------------

class TestBuildHighlightPlan:
    def test_single_video_all_budget(self):
        scenes = _consecutive_scenes("v1", 10, duration_ms=45000)  # 450s total
        plan = build_highlight_plan(scenes, _request(target_s=120))
        assert plan.videos_used == 1
        assert plan.total_duration_ms <= 120000
        assert plan.total_duration_ms > 0
        assert len(plan.clips) >= 1

    def test_multi_video_even_distribution(self):
        scenes = [
            *_consecutive_scenes("v1", 5),
            *_consecutive_scenes("v2", 5),
            *_consecutive_scenes("v3", 5),
        ]
        plan = build_highlight_plan(scenes, _request(target_s=60))
        assert plan.videos_used >= 2  # should use multiple videos
        assert plan.total_duration_ms <= 60000

    def test_excluded_videos_filtered(self):
        scenes = [
            *_consecutive_scenes("v1", 5),
            *_consecutive_scenes("v2", 5),
        ]
        plan = build_highlight_plan(scenes, _request(target_s=60, excluded={"v1"}))
        assert all(c.video_id != "v1" for c in plan.clips)
        assert plan.videos_used == 1
        assert plan.videos_available == 1

    def test_empty_after_exclusion(self):
        scenes = _consecutive_scenes("v1", 5)
        plan = build_highlight_plan(scenes, _request(target_s=60, excluded={"v1"}))
        assert plan.clips == []
        assert plan.total_duration_ms == 0
        assert plan.videos_used == 0

    def test_no_scenes_returns_empty_plan(self):
        plan = build_highlight_plan([], _request(target_s=60))
        assert plan.clips == []
        assert plan.total_duration_ms == 0

    def test_insufficient_content_uses_all_available(self):
        # Only 20s of content for a 120s request
        scenes = [_scene("s1", "v1", 0, 20000)]
        plan = build_highlight_plan(scenes, _request(target_s=120))
        assert plan.total_duration_ms == 20000
        assert len(plan.clips) == 1

    def test_timeline_positions_non_overlapping(self):
        scenes = [
            *_consecutive_scenes("v1", 8),
            *_consecutive_scenes("v2", 8),
            *_consecutive_scenes("v3", 8),
        ]
        plan = build_highlight_plan(scenes, _request(target_s=120))
        for i in range(1, len(plan.clips)):
            prev_end = plan.clips[i - 1].timeline_start_ms + plan.clips[i - 1].duration_ms
            assert plan.clips[i].timeline_start_ms == prev_end, (
                f"Clip {i} starts at {plan.clips[i].timeline_start_ms} but prev ends at {prev_end}"
            )

    def test_total_duration_never_exceeds_target(self):
        scenes = [
            *_consecutive_scenes("v1", 20),
            *_consecutive_scenes("v2", 20),
        ]
        for target_s in [30, 60, 120, 180, 300]:
            plan = build_highlight_plan(scenes, _request(target_s=target_s))
            assert plan.total_duration_ms <= target_s * 1000, (
                f"target={target_s}s but got {plan.total_duration_ms}ms"
            )

    def test_30s_minimum_target(self):
        scenes = _consecutive_scenes("v1", 10)
        plan = build_highlight_plan(scenes, _request(target_s=30))
        assert plan.total_duration_ms <= 30000
        assert plan.total_duration_ms > 0

    def test_300s_maximum_target(self):
        scenes = []
        for i in range(10):
            scenes.extend(_consecutive_scenes(f"v{i}", 15))
        plan = build_highlight_plan(scenes, _request(target_s=300))
        assert plan.total_duration_ms <= 300000

    def test_target_below_minimum_clamped(self):
        scenes = _consecutive_scenes("v1", 5)
        plan = build_highlight_plan(scenes, _request(target_s=5))  # below 30s min
        # Should clamp to 30s
        assert plan.total_duration_ms <= 30000

    def test_target_above_maximum_clamped(self):
        scenes = []
        for i in range(5):
            scenes.extend(_consecutive_scenes(f"v{i}", 20))
        plan = build_highlight_plan(scenes, _request(target_s=600))  # above 300s max
        assert plan.total_duration_ms <= 300000

    def test_clips_within_same_video_are_chronological(self):
        scenes = [
            *_consecutive_scenes("v1", 3, start_offset=0),
            *_consecutive_scenes("v1", 3, start_offset=300000),
        ]
        plan = build_highlight_plan(scenes, _request(target_s=300))
        v1_clips = [c for c in plan.clips if c.video_id == "v1"]
        for i in range(1, len(v1_clips)):
            assert v1_clips[i].start_ms >= v1_clips[i - 1].start_ms

    def test_maximizes_video_diversity(self):
        # 5 videos each with 60s of content, target 60s → should use 5+ videos
        scenes = [
            *_consecutive_scenes("v1", 2, duration_ms=30000),
            *_consecutive_scenes("v2", 2, duration_ms=30000),
            *_consecutive_scenes("v3", 2, duration_ms=30000),
            *_consecutive_scenes("v4", 2, duration_ms=30000),
            *_consecutive_scenes("v5", 2, duration_ms=30000),
        ]
        plan = build_highlight_plan(scenes, _request(target_s=60))
        assert plan.videos_used >= 3  # should spread across videos

    def test_very_short_scenes_filtered(self):
        scenes = [
            _scene("s1", "v1", 0, 500),       # 500ms — too short, filtered
            _scene("s2", "v1", 1000, 46000),   # 45s — kept
        ]
        plan = build_highlight_plan(scenes, _request(target_s=60))
        assert plan.total_duration_ms == 45000
        assert len(plan.clips) == 1


# ---------------------------------------------------------------------------
# Real-world data patterns (from staging analysis)
# ---------------------------------------------------------------------------

class TestRealWorldPatterns:
    def test_373_scenes_single_video_45s_each(self):
        """Top person on staging: 373 scenes, 1 video, all 45s."""
        scenes = _consecutive_scenes("gd_0032aa97cdfbe54e", 373, duration_ms=45000)
        plan = build_highlight_plan(scenes, _request(target_s=120))
        assert plan.videos_used == 1
        assert plan.total_duration_ms <= 120000
        assert plan.total_duration_ms > 100000  # should use most of budget

    def test_120_scenes_across_6_videos(self):
        """Multi-video person: 120 scenes across 6 videos, 45s each."""
        scenes = []
        for i, count in enumerate([30, 30, 24, 12, 12, 12]):
            vid = f"gd_video_{i}"
            scenes.extend(_consecutive_scenes(vid, count, duration_ms=45000))
        plan = build_highlight_plan(scenes, _request(target_s=120))
        assert plan.videos_used >= 3  # should use multiple videos
        assert plan.total_duration_ms <= 120000

    def test_5min_highlight_from_diverse_person(self):
        """5 minute highlight from person appearing in 6 videos."""
        scenes = []
        for i in range(6):
            vid = f"gd_video_{i}"
            scenes.extend(_consecutive_scenes(vid, 15, duration_ms=45000))
        plan = build_highlight_plan(scenes, _request(target_s=300))
        assert plan.videos_used >= 4
        assert plan.total_duration_ms <= 300000
        assert plan.total_duration_ms > 250000

    def test_person_with_mixed_scene_durations(self):
        """Person with mix of fine (3s) and coarse (45s) scenes."""
        scenes = [
            *_consecutive_scenes("v1", 5, duration_ms=3000),    # 15s total
            *_consecutive_scenes("v2", 3, duration_ms=45000),   # 135s total
            *_consecutive_scenes("v3", 10, duration_ms=6000),   # 60s total
        ]
        plan = build_highlight_plan(scenes, _request(target_s=60))
        assert plan.videos_used >= 2
        assert plan.total_duration_ms <= 60000
