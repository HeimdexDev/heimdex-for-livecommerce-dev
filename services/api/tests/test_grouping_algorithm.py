# pyright: reportUnknownMemberType=false, reportUnusedFunction=false
"""
Unit tests for the scene grouping algorithm (pure functions).

Tests cover:
1. _dot_product — basic math, edge cases (empty, mismatched)
2. compute_pairwise_similarity — adaptive signal fusion, all 4 branches
3. _compute_adaptive_threshold — mean-stdev computation, edge cases
4. find_group_boundaries — adaptive threshold, explicit override, edge cases
5. _merge_small_groups — undersized group merging with None similarities
6. Integration — end-to-end with sparse embeddings, production-scale videos

Run with: pytest tests/test_grouping_algorithm.py -v
"""

import math

import pytest

from app.modules.grouping.algorithm import (
    _compute_adaptive_threshold,
    _dot_product,
    _merge_small_groups,
    compute_pairwise_similarity,
    find_group_boundaries,
)


# ======================================================================
# Helpers
# ======================================================================


def _make_scene(
    start_ms: int = 0,
    *,
    text_emb: list[float] | None = None,
    vis_emb: list[float] | None = None,
) -> dict[str, object]:
    scene: dict[str, object] = {
        "scene_id": f"scene_{start_ms}",
        "start_ms": start_ms,
        "end_ms": start_ms + 10_000,
    }
    if text_emb is not None:
        scene["embedding_vector"] = text_emb
    if vis_emb is not None:
        scene["visual_embedding"] = vis_emb
    return scene


def _unit_vec(dim: int, idx: int = 0) -> list[float]:
    v = [0.0] * dim
    v[idx % dim] = 1.0
    return v


def _uniform_vec(dim: int, value: float = 1.0) -> list[float]:
    norm = math.sqrt(dim) * abs(value)
    if norm == 0:
        return [0.0] * dim
    return [value / norm] * dim


# ======================================================================
# _dot_product
# ======================================================================


class TestDotProduct:
    def test_identical_unit_vectors(self) -> None:
        v = _unit_vec(3, 0)
        assert _dot_product(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self) -> None:
        a = _unit_vec(3, 0)
        b = _unit_vec(3, 1)
        assert _dot_product(a, b) == pytest.approx(0.0)

    def test_simple_dot(self) -> None:
        assert _dot_product([1.0, 2.0, 3.0], [4.0, 5.0, 6.0]) == pytest.approx(32.0)

    def test_empty_vectors(self) -> None:
        assert _dot_product([], []) == 0.0

    def test_mismatched_lengths(self) -> None:
        assert _dot_product([1.0, 2.0], [1.0]) == 0.0

    def test_one_empty(self) -> None:
        assert _dot_product([1.0], []) == 0.0
        assert _dot_product([], [1.0]) == 0.0

    def test_single_element(self) -> None:
        assert _dot_product([0.5], [0.5]) == pytest.approx(0.25)


# ======================================================================
# compute_pairwise_similarity
# ======================================================================


class TestComputePairwiseSimilarity:
    def test_empty_scenes(self) -> None:
        assert compute_pairwise_similarity([]) == []

    def test_single_scene(self) -> None:
        assert compute_pairwise_similarity([_make_scene(0)]) == []

    def test_two_identical_scenes_text_only(self) -> None:
        v = _uniform_vec(4)
        scenes = [
            _make_scene(0, text_emb=v),
            _make_scene(10000, text_emb=v),
        ]
        sims = compute_pairwise_similarity(scenes)
        assert len(sims) == 1
        assert sims[0] == pytest.approx(1.0, abs=1e-6)

    def test_two_orthogonal_scenes_text_only(self) -> None:
        scenes = [
            _make_scene(0, text_emb=_unit_vec(4, 0)),
            _make_scene(10000, text_emb=_unit_vec(4, 1)),
        ]
        sims = compute_pairwise_similarity(scenes)
        assert len(sims) == 1
        assert sims[0] == pytest.approx(0.0)

    def test_visual_only(self) -> None:
        v = _uniform_vec(3)
        scenes = [
            _make_scene(0, vis_emb=v),
            _make_scene(10000, vis_emb=v),
        ]
        sims = compute_pairwise_similarity(scenes)
        assert sims[0] == pytest.approx(1.0, abs=1e-6)

    def test_both_signals_weighted(self) -> None:
        text_v = _uniform_vec(4)
        scenes = [
            _make_scene(0, text_emb=text_v, vis_emb=_unit_vec(3, 0)),
            _make_scene(10000, text_emb=text_v, vis_emb=_unit_vec(3, 1)),
        ]
        sims = compute_pairwise_similarity(scenes)
        # expected: (0.6 * 1.0 + 0.4 * 0.0) / (0.6 + 0.4) = 0.6
        assert sims[0] == pytest.approx(0.6, abs=1e-6)

    def test_no_embeddings_returns_none(self) -> None:
        scenes = [_make_scene(0), _make_scene(10000)]
        sims = compute_pairwise_similarity(scenes)
        assert sims[0] is None

    def test_partial_embeddings_mixed(self) -> None:
        v = _uniform_vec(4)
        scenes = [
            _make_scene(0, text_emb=v),
            _make_scene(10000, text_emb=v),
            _make_scene(20000),  # no embeddings
        ]
        sims = compute_pairwise_similarity(scenes)
        assert len(sims) == 2
        assert sims[0] == pytest.approx(1.0, abs=1e-6)  # both have text
        assert sims[1] is None  # second has no embedding

    def test_one_side_missing_text(self) -> None:
        v = _uniform_vec(4)
        scenes = [
            _make_scene(0, text_emb=v),
            _make_scene(10000),  # no embedding
        ]
        sims = compute_pairwise_similarity(scenes)
        assert sims[0] is None

    def test_custom_weights(self) -> None:
        text_v = _uniform_vec(4)
        vis_v = _uniform_vec(3)
        scenes = [
            _make_scene(0, text_emb=text_v, vis_emb=vis_v),
            _make_scene(10000, text_emb=text_v, vis_emb=_unit_vec(3, 1)),
        ]
        sims = compute_pairwise_similarity(
            scenes, text_weight=0.3, visual_weight=0.7,
        )
        vis_sim = _dot_product(vis_v, _unit_vec(3, 1))
        expected = (0.3 * 1.0 + 0.7 * vis_sim) / (0.3 + 0.7)
        assert sims[0] == pytest.approx(expected, abs=1e-6)

    def test_clamping(self) -> None:
        big = [10.0, 10.0]
        scenes = [
            _make_scene(0, text_emb=big),
            _make_scene(10000, text_emb=big),
        ]
        sims = compute_pairwise_similarity(scenes)
        assert sims[0] == 1.0  # clamped

    def test_three_scenes_returns_two_scores(self) -> None:
        v = _uniform_vec(4)
        scenes = [
            _make_scene(0, text_emb=v),
            _make_scene(10000, text_emb=v),
            _make_scene(20000, text_emb=v),
        ]
        sims = compute_pairwise_similarity(scenes)
        assert len(sims) == 2

    def test_n_scenes_returns_n_minus_1_scores(self) -> None:
        v = _uniform_vec(4)
        n = 10
        scenes = [_make_scene(i * 10000, text_emb=v) for i in range(n)]
        sims = compute_pairwise_similarity(scenes)
        assert len(sims) == n - 1

    def test_sparse_embedding_pattern(self) -> None:
        """Simulate production pattern: ~30% of pairs have embeddings."""
        v1 = _uniform_vec(4)
        v2 = _uniform_vec(4, value=0.5)
        scenes = [
            _make_scene(0, text_emb=v1),      # has embedding
            _make_scene(10000, text_emb=v1),   # has embedding → pair 0 real
            _make_scene(20000),                # no embedding → pair 1 None
            _make_scene(30000),                # no embedding → pair 2 None
            _make_scene(40000, text_emb=v2),   # has embedding → pair 3 None
            _make_scene(50000, text_emb=v2),   # has embedding → pair 4 real
            _make_scene(60000),                # no embedding → pair 5 None
        ]
        sims = compute_pairwise_similarity(scenes)
        assert len(sims) == 6
        assert sims[0] == pytest.approx(1.0, abs=1e-6)  # v1·v1
        assert sims[1] is None   # has_emb · no_emb
        assert sims[2] is None   # no_emb · no_emb
        assert sims[3] is None   # no_emb · has_emb
        assert sims[4] == pytest.approx(1.0, abs=1e-6)  # v2·v2
        assert sims[5] is None   # has_emb · no_emb


# ======================================================================
# _compute_adaptive_threshold
# ======================================================================


class TestComputeAdaptiveThreshold:
    def test_basic_computation(self) -> None:
        # mean=0.8, stdev=0.1, sensitivity=1.0 → threshold=0.7
        sims: list[float | None] = [0.7, 0.8, 0.9]
        threshold = _compute_adaptive_threshold(sims, sensitivity=1.0)
        mean = 0.8
        variance = ((0.7 - 0.8) ** 2 + (0.8 - 0.8) ** 2 + (0.9 - 0.8) ** 2) / 3
        stdev = math.sqrt(variance)
        assert threshold == pytest.approx(mean - 1.0 * stdev, abs=1e-6)

    def test_ignores_none_values(self) -> None:
        # Only real values used for computation
        sims: list[float | None] = [0.8, None, 0.9, None, None, 0.7]
        threshold_with_none = _compute_adaptive_threshold(sims, sensitivity=1.0)
        threshold_without = _compute_adaptive_threshold([0.8, 0.9, 0.7], sensitivity=1.0)
        assert threshold_with_none == pytest.approx(threshold_without, abs=1e-9)

    def test_all_none_uses_fallback(self) -> None:
        sims: list[float | None] = [None, None, None]
        threshold = _compute_adaptive_threshold(sims, fallback_threshold=0.42)
        assert threshold == 0.42

    def test_single_real_value_uses_fallback(self) -> None:
        # Need at least 2 real values for meaningful statistics
        sims: list[float | None] = [0.8, None, None]
        threshold = _compute_adaptive_threshold(sims, fallback_threshold=0.55)
        assert threshold == 0.55

    def test_two_real_values_computes(self) -> None:
        sims: list[float | None] = [0.8, None, 0.9]
        threshold = _compute_adaptive_threshold(sims, sensitivity=1.0)
        mean = 0.85
        variance = ((0.8 - 0.85) ** 2 + (0.9 - 0.85) ** 2) / 2
        stdev = math.sqrt(variance)
        assert threshold == pytest.approx(mean - stdev, abs=1e-6)

    def test_zero_sensitivity_equals_mean(self) -> None:
        sims: list[float | None] = [0.7, 0.8, 0.9]
        threshold = _compute_adaptive_threshold(sims, sensitivity=0.0)
        assert threshold == pytest.approx(0.8, abs=1e-6)

    def test_high_sensitivity_lower_threshold(self) -> None:
        sims: list[float | None] = [0.7, 0.8, 0.9]
        t1 = _compute_adaptive_threshold(sims, sensitivity=1.0)
        t2 = _compute_adaptive_threshold(sims, sensitivity=2.0)
        assert t2 < t1

    def test_identical_values_zero_stdev(self) -> None:
        sims: list[float | None] = [0.8, 0.8, 0.8, 0.8]
        threshold = _compute_adaptive_threshold(sims, sensitivity=1.0)
        # stdev=0, so threshold=mean=0.8
        assert threshold == pytest.approx(0.8, abs=1e-6)

    def test_production_like_distribution(self) -> None:
        """Simulate real staging data: mean ~0.80, stdev ~0.04."""
        sims: list[float | None] = [
            0.82, 0.79, None, None, 0.83, None, 0.78,
            None, None, None, 0.81, 0.76, None, 0.84,
            None, None, 0.80, None, 0.77, None,
        ]
        threshold = _compute_adaptive_threshold(sims, sensitivity=1.0)
        # With real values [0.82, 0.79, 0.83, 0.78, 0.81, 0.76, 0.84, 0.80, 0.77]
        real = [0.82, 0.79, 0.83, 0.78, 0.81, 0.76, 0.84, 0.80, 0.77]
        mean = sum(real) / len(real)
        variance = sum((s - mean) ** 2 for s in real) / len(real)
        stdev = math.sqrt(variance)
        expected = mean - stdev
        assert threshold == pytest.approx(expected, abs=1e-6)
        # Should be around 0.76-0.77, NOT 0.55
        assert threshold > 0.70

    def test_empty_list_uses_fallback(self) -> None:
        threshold = _compute_adaptive_threshold([], fallback_threshold=0.55)
        assert threshold == 0.55


# ======================================================================
# find_group_boundaries
# ======================================================================


class TestFindGroupBoundaries:
    def test_empty(self) -> None:
        assert find_group_boundaries([], 0) == []

    def test_single_scene(self) -> None:
        assert find_group_boundaries([], 1) == [(0, 0)]

    def test_no_similarities(self) -> None:
        assert find_group_boundaries([], 2) == [(0, 1)]

    def test_all_above_threshold_explicit(self) -> None:
        sims: list[float | None] = [0.8, 0.9, 0.7]
        result = find_group_boundaries(sims, 4, threshold=0.55)
        assert result == [(0, 3)]

    def test_all_below_threshold_explicit(self) -> None:
        sims: list[float | None] = [0.1, 0.1, 0.1]
        result = find_group_boundaries(sims, 4, threshold=0.55, min_group_size=1)
        assert len(result) == 4
        assert result == [(0, 0), (1, 1), (2, 2), (3, 3)]

    def test_single_boundary_explicit(self) -> None:
        sims: list[float | None] = [0.9, 0.1, 0.9]
        result = find_group_boundaries(sims, 4, threshold=0.55, min_group_size=1)
        assert result == [(0, 1), (2, 3)]

    def test_multiple_boundaries_explicit(self) -> None:
        sims: list[float | None] = [0.9, 0.1, 0.9, 0.1]
        result = find_group_boundaries(sims, 5, threshold=0.55, min_group_size=1)
        assert result == [(0, 1), (2, 3), (4, 4)]

    def test_exact_threshold_no_boundary(self) -> None:
        sims: list[float | None] = [0.55]
        result = find_group_boundaries(sims, 2, threshold=0.55)
        assert result == [(0, 1)]

    def test_just_below_threshold_creates_boundary(self) -> None:
        sims: list[float | None] = [0.549]
        result = find_group_boundaries(sims, 2, threshold=0.55, min_group_size=1)
        assert result == [(0, 0), (1, 1)]

    def test_coverage_invariant(self) -> None:
        sims: list[float | None] = [0.9, 0.1, 0.8, 0.2, 0.7]
        result = find_group_boundaries(sims, 6, threshold=0.55, min_group_size=1)
        assert result[0][0] == 0
        assert result[-1][1] == 5
        for i in range(len(result) - 1):
            assert result[i][1] + 1 == result[i + 1][0]

    def test_custom_threshold(self) -> None:
        sims: list[float | None] = [0.3, 0.4, 0.5]
        result = find_group_boundaries(sims, 4, threshold=0.35, min_group_size=1)
        assert result == [(0, 0), (1, 3)]

    def test_none_values_skip_boundary(self) -> None:
        """None similarities never create boundaries."""
        sims: list[float | None] = [0.9, None, None, 0.9]
        result = find_group_boundaries(sims, 5, threshold=0.55)
        assert result == [(0, 4)]

    def test_all_none_single_group(self) -> None:
        """All None similarities → no boundaries → single group."""
        sims: list[float | None] = [None, None, None, None]
        result = find_group_boundaries(sims, 5)
        assert result == [(0, 4)]

    def test_adaptive_threshold_default(self) -> None:
        """Without explicit threshold, uses adaptive (mean - 1*stdev)."""
        # Values: 0.9, 0.85, 0.3, 0.88
        # mean=0.7325, stdev≈0.2464, adaptive≈0.486
        # Only 0.3 is below → boundary after scene 2
        sims: list[float | None] = [0.9, 0.85, 0.3, 0.88]
        result = find_group_boundaries(sims, 5, min_group_size=1)
        assert len(result) == 2
        assert result == [(0, 2), (3, 4)]

    def test_adaptive_with_none_mixed(self) -> None:
        """Adaptive threshold computed from real values only, None skipped."""
        sims: list[float | None] = [0.8, None, 0.6, None, 0.82]
        # Real values: [0.8, 0.6, 0.82], mean=0.74, stdev≈0.0972
        # Adaptive ≈ 0.74 - 0.0972 ≈ 0.6428
        # 0.6 < 0.6428 → boundary after scene 2
        result = find_group_boundaries(sims, 6, min_group_size=1)
        assert len(result) == 2
        assert result[0] == (0, 2)
        assert result[1] == (3, 5)

    def test_explicit_threshold_overrides_adaptive(self) -> None:
        """Explicit threshold takes precedence over adaptive."""
        sims: list[float | None] = [0.8, 0.82, 0.79, 0.81]
        # Adaptive would keep as one group, but explicit 0.85 splits more
        result_explicit = find_group_boundaries(sims, 5, threshold=0.85, min_group_size=1)
        result_adaptive = find_group_boundaries(sims, 5, min_group_size=1)
        # Explicit: all values < 0.85 → many boundaries
        assert len(result_explicit) > len(result_adaptive)


# ======================================================================
# _merge_small_groups
# ======================================================================


class TestMergeSmallGroups:
    def test_no_small_groups(self) -> None:
        groups = [(0, 2), (3, 5)]
        sims: list[float | None] = [0.9, 0.9, 0.1, 0.9, 0.9]
        result = _merge_small_groups(groups, sims, min_group_size=2)
        assert result == [(0, 2), (3, 5)]

    def test_single_group_stays(self) -> None:
        groups = [(0, 0)]
        sims: list[float | None] = []
        result = _merge_small_groups(groups, sims, min_group_size=2)
        assert result == [(0, 0)]

    def test_small_middle_merges_into_higher_sim_neighbor(self) -> None:
        groups = [(0, 2), (3, 3), (4, 6)]
        sims: list[float | None] = [0.9, 0.9, 0.3, 0.8, 0.9, 0.9]
        result = _merge_small_groups(groups, sims, min_group_size=2)
        assert (3, 3) not in result
        assert result[0][0] == 0
        assert result[-1][1] == 6

    def test_small_at_start_merges_right(self) -> None:
        groups = [(0, 0), (1, 3)]
        sims: list[float | None] = [0.4, 0.9, 0.9]
        result = _merge_small_groups(groups, sims, min_group_size=2)
        assert result == [(0, 3)]

    def test_small_at_end_merges_left(self) -> None:
        groups = [(0, 2), (3, 3)]
        sims: list[float | None] = [0.9, 0.9, 0.4]
        result = _merge_small_groups(groups, sims, min_group_size=2)
        assert result == [(0, 3)]

    def test_min_group_size_3(self) -> None:
        groups = [(0, 1), (2, 4)]
        sims: list[float | None] = [0.9, 0.2, 0.9, 0.9]
        result = _merge_small_groups(groups, sims, min_group_size=3)
        assert result == [(0, 4)]

    def test_none_similarity_at_boundary(self) -> None:
        """None similarity at boundary → treated as -1.0 (least preferred)."""
        groups = [(0, 2), (3, 3), (4, 6)]
        # left boundary: None, right boundary: 0.7
        sims: list[float | None] = [0.9, 0.9, None, 0.7, 0.9, 0.9]
        result = _merge_small_groups(groups, sims, min_group_size=2)
        # Should merge right (0.7 > -1.0)
        assert result == [(0, 2), (3, 6)]


# ======================================================================
# Integration: compute_pairwise_similarity → find_group_boundaries
# ======================================================================


class TestAlgorithmIntegration:
    def test_identical_scenes_one_group(self) -> None:
        v = _uniform_vec(8)
        scenes = [_make_scene(i * 10000, text_emb=v) for i in range(5)]
        sims = compute_pairwise_similarity(scenes)
        groups = find_group_boundaries(sims, len(scenes))
        assert len(groups) == 1
        assert groups[0] == (0, 4)

    def test_two_distinct_clusters(self) -> None:
        v1 = _unit_vec(8, 0)
        v2 = _unit_vec(8, 4)
        scenes = [
            _make_scene(0, text_emb=v1),
            _make_scene(10000, text_emb=v1),
            _make_scene(20000, text_emb=v1),
            _make_scene(30000, text_emb=v2),
            _make_scene(40000, text_emb=v2),
            _make_scene(50000, text_emb=v2),
        ]
        sims = compute_pairwise_similarity(scenes)
        # Adaptive: real sims = [1.0, 1.0, 0.0, 1.0, 1.0]
        # mean=0.8, stdev≈0.4, threshold≈0.4 → 0.0 < 0.4 → boundary
        groups = find_group_boundaries(sims, len(scenes))
        assert len(groups) == 2
        assert groups[0] == (0, 2)
        assert groups[1] == (3, 5)

    def test_gradual_transition(self) -> None:
        dim = 4
        scenes = []
        for i in range(6):
            v = [0.0] * dim
            v[i % dim] = 1.0
            scenes.append(_make_scene(i * 10000, text_emb=v))

        sims = compute_pairwise_similarity(scenes)
        for s in sims:
            assert s == pytest.approx(0.0)

        groups = find_group_boundaries(sims, len(scenes), threshold=0.55, min_group_size=1)
        assert len(groups) == 6

    def test_no_embeddings_single_group(self) -> None:
        """Scenes without embeddings → all None → no boundaries → single group."""
        scenes = [_make_scene(i * 10000) for i in range(4)]
        sims = compute_pairwise_similarity(scenes)
        assert all(s is None for s in sims)
        groups = find_group_boundaries(sims, len(scenes))
        assert len(groups) == 1
        assert groups[0] == (0, 3)

    def test_large_video_coverage(self) -> None:
        n = 100
        v = _uniform_vec(4)
        scenes = [_make_scene(i * 10000, text_emb=v) for i in range(n)]
        scenes[30] = _make_scene(300000, text_emb=_unit_vec(4, 2))
        scenes[60] = _make_scene(600000, text_emb=_unit_vec(4, 3))

        sims = compute_pairwise_similarity(scenes)
        groups = find_group_boundaries(sims, n)

        assert groups[0][0] == 0
        assert groups[-1][1] == n - 1
        for i in range(len(groups) - 1):
            assert groups[i][1] + 1 == groups[i + 1][0], f"Gap at group {i}"

    def test_sparse_embeddings_production_scenario(self) -> None:
        """Simulate production: 70% of scenes lack embeddings.

        This was the root cause bug: neutral 0.5 scores created false
        boundaries which cascade-merged into one giant group. With
        adaptive threshold + None sentinel, we should get meaningful
        groups where real similarity dips occur.

        Key: the topic boundary must have adjacent scenes with embeddings
        on BOTH sides for the algorithm to detect it.
        """
        n = 50
        scenes = []
        v_topic_a = _uniform_vec(8)
        v_topic_b = _unit_vec(8, 4)

        for i in range(n):
            topic = v_topic_a if i < 25 else v_topic_b
            # ~30% of scenes get embeddings (roughly every 3rd)
            if i % 3 == 0:
                scenes.append(_make_scene(i * 10000, text_emb=topic))
            else:
                scenes.append(_make_scene(i * 10000))

        # Ensure the topic boundary is detectable: both scene 24 and 25
        # must have embeddings (on different topics)
        scenes[24] = _make_scene(240000, text_emb=v_topic_a)
        scenes[25] = _make_scene(250000, text_emb=v_topic_b)

        sims = compute_pairwise_similarity(scenes)

        # Count None vs real
        none_count = sum(1 for s in sims if s is None)
        real_count = len(sims) - none_count
        assert none_count > real_count  # majority are None

        groups = find_group_boundaries(sims, n)

        # Coverage invariant
        assert groups[0][0] == 0
        assert groups[-1][1] == n - 1
        for i in range(len(groups) - 1):
            assert groups[i][1] + 1 == groups[i + 1][0]

        # Should NOT be a single group (the old bug)
        assert len(groups) >= 2, (
            f"Expected multiple groups for topic-change video, got {len(groups)}"
        )

    def test_all_high_similarity_single_group(self) -> None:
        """When all scenes are very similar, adaptive threshold keeps them together."""
        v = _uniform_vec(8)
        # Small perturbations → high similarity but not identical
        scenes = []
        for i in range(20):
            perturbed = list(v)
            perturbed[i % 8] += 0.001 * i
            # Renormalize
            norm = math.sqrt(sum(x ** 2 for x in perturbed))
            perturbed = [x / norm for x in perturbed]
            scenes.append(_make_scene(i * 10000, text_emb=perturbed))

        sims = compute_pairwise_similarity(scenes)
        groups = find_group_boundaries(sims, len(scenes))

        # All very similar → should be 1 group (or very few)
        assert len(groups) <= 3

    def test_interleaved_sparse_and_dense(self) -> None:
        """Dense embedding region followed by sparse region."""
        v1 = _uniform_vec(8)
        v2 = _unit_vec(8, 4)

        scenes = []
        # Dense region (scenes 0-9): all have embeddings, same topic
        for i in range(10):
            scenes.append(_make_scene(i * 10000, text_emb=v1))

        # Sparse transition (scenes 10-14): no embeddings
        for i in range(10, 15):
            scenes.append(_make_scene(i * 10000))

        # Dense region (scenes 15-24): all have embeddings, different topic
        for i in range(15, 25):
            scenes.append(_make_scene(i * 10000, text_emb=v2))

        sims = compute_pairwise_similarity(scenes)
        groups = find_group_boundaries(sims, len(scenes))

        # Coverage
        assert groups[0][0] == 0
        assert groups[-1][1] == 24

        # The sparse region acts as a bridge (no boundaries placed there)
        # The dense regions are internally consistent
        # We expect the real boundary to come from the dense-to-sparse
        # or sparse-to-dense transitions where one side has embeddings
        # and the other doesn't (→ None, not a boundary)
        assert len(groups) >= 1

    def test_sensitivity_parameter_effect(self) -> None:
        """Lower sensitivity = more groups, higher = fewer groups."""
        v1 = _uniform_vec(8)
        v2 = _unit_vec(8, 4)
        v3 = _unit_vec(8, 6)

        scenes = [
            _make_scene(0, text_emb=v1),
            _make_scene(10000, text_emb=v1),
            _make_scene(20000, text_emb=v2),
            _make_scene(30000, text_emb=v2),
            _make_scene(40000, text_emb=v3),
            _make_scene(50000, text_emb=v3),
        ]

        sims = compute_pairwise_similarity(scenes)

        # sensitivity=0.5 → threshold closer to mean → more boundaries
        groups_sensitive = find_group_boundaries(
            sims, len(scenes), sensitivity=0.5, min_group_size=1,
        )
        # sensitivity=2.0 → threshold further below mean → fewer boundaries
        groups_permissive = find_group_boundaries(
            sims, len(scenes), sensitivity=2.0, min_group_size=1,
        )

        assert len(groups_sensitive) >= len(groups_permissive)
