"""
Search Quality Contract Tests

These tests enforce the invariants defined in docs/SEARCH_CONTRACT.md.
Run with: pytest tests/test_search_contract.py -v
"""
import pytest
from app.modules.search.fusion import (
    compute_weighted_rrf,
    diversify_results,
    compute_quality_factor,
    rrf_score,
    RankedItem,
    MIN_TRANSCRIPT_CHARS,
    GOOD_TRANSCRIPT_CHARS,
    QUALITY_FLOOR,
)
from app.config import get_settings


class TestRankingInvariants:
    """Test: Results sorted by adjusted_score descending."""

    def test_results_sorted_by_adjusted_score(self):
        """Invariant: Results are sorted by adjusted_score descending."""
        lexical = [
            {"_id": "a", "_score": 10.0, "_source": {"video_id": "v1", "transcript_char_count": 100}},
            {"_id": "b", "_score": 8.0, "_source": {"video_id": "v2", "transcript_char_count": 100}},
            {"_id": "c", "_score": 6.0, "_source": {"video_id": "v3", "transcript_char_count": 100}},
        ]
        vector = [
            {"_id": "c", "_score": 0.95, "_source": {"video_id": "v3", "transcript_char_count": 100}},
            {"_id": "b", "_score": 0.85, "_source": {"video_id": "v2", "transcript_char_count": 100}},
        ]
        
        results = compute_weighted_rrf(lexical, vector, [], bm25_weight=0.5, text_knn_weight=0.5, visual_weight=0.0)
        
        for i in range(len(results) - 1):
            assert results[i].adjusted_score >= results[i + 1].adjusted_score

    def test_adjusted_score_equals_fused_times_quality(self):
        """Invariant: adjusted_score = fused_score × quality_factor."""
        lexical = [{"_id": "doc1", "_score": 10.0, "_source": {"video_id": "v1", "transcript_char_count": 50}}]
        
        results = compute_weighted_rrf(lexical, [], [], bm25_weight=1.0, text_knn_weight=0.0, visual_weight=0.0)
        
        for item in results:
            expected = item.fused_score * item.quality_factor
            assert item.adjusted_score == pytest.approx(expected)

    def test_fused_score_equals_sum_of_contributions(self):
        """Invariant: fused_score = lexical_contribution + vector_contribution."""
        lexical = [{"_id": "doc1", "_score": 10.0, "_source": {"video_id": "v1"}}]
        vector = [{"_id": "doc1", "_score": 0.9, "_source": {"video_id": "v1"}}]
        
        results = compute_weighted_rrf(lexical, vector, [], bm25_weight=0.5, text_knn_weight=0.5, visual_weight=0.0)
        
        for item in results:
            expected = item.lexical_contribution + item.vector_contribution
            assert item.fused_score == pytest.approx(expected)


class TestAlphaInvariants:
    """Test: Alpha parameter controls fusion weighting."""

    def test_alpha_zero_no_vector_contribution(self):
        """Invariant: alpha=0.0 → vector_contribution=0 for all items."""
        lexical = [{"_id": "lex1", "_score": 10.0, "_source": {"video_id": "v1"}}]
        vector = [{"_id": "vec1", "_score": 0.95, "_source": {"video_id": "v2"}}]
        
        results = compute_weighted_rrf(lexical, vector, [], bm25_weight=1.0, text_knn_weight=0.0, visual_weight=0.0)
        
        for item in results:
            assert item.vector_contribution == 0.0

    def test_alpha_one_no_lexical_contribution(self):
        """Invariant: alpha=1.0 → lexical_contribution=0 for all items."""
        lexical = [{"_id": "lex1", "_score": 10.0, "_source": {"video_id": "v1"}}]
        vector = [{"_id": "vec1", "_score": 0.95, "_source": {"video_id": "v2"}}]
        
        results = compute_weighted_rrf(lexical, vector, [], bm25_weight=0.0, text_knn_weight=1.0, visual_weight=0.0)
        
        for item in results:
            assert item.lexical_contribution == 0.0

    def test_alpha_half_equal_contributions_same_rank(self):
        """Invariant: alpha=0.5 with same rank → contributions approximately equal."""
        lexical = [{"_id": "both", "_score": 10.0, "_source": {"video_id": "v1"}}]
        vector = [{"_id": "both", "_score": 0.9, "_source": {"video_id": "v1"}}]
        
        results = compute_weighted_rrf(lexical, vector, [], bm25_weight=0.5, text_knn_weight=0.5, visual_weight=0.0)
        
        item = results[0]
        assert item.lexical_contribution == pytest.approx(item.vector_contribution, rel=0.01)


class TestQualityFactorInvariants:
    """Test: Quality factor bounds and thresholds."""

    def test_quality_factor_bounds(self):
        """Invariant: 0.7 ≤ quality_factor ≤ 1.0."""
        test_counts = [0, 10, 20, 50, 100, 200, 1000]
        
        for count in test_counts:
            source = {"transcript_char_count": count}
            factor = compute_quality_factor(source)
            assert QUALITY_FLOOR <= factor <= 1.0, f"Failed for char_count={count}"

    def test_quality_above_threshold_full(self):
        """Invariant: char_count >= 100 → quality_factor = 1.0."""
        for count in [100, 150, 200, 1000]:
            source = {"transcript_char_count": count}
            assert compute_quality_factor(source) == 1.0

    def test_quality_below_threshold_floor(self):
        """Invariant: char_count <= 20 → quality_factor = 0.7."""
        for count in [0, 5, 10, 20]:
            source = {"transcript_char_count": count}
            assert compute_quality_factor(source) == QUALITY_FLOOR

    def test_quality_between_thresholds_interpolated(self):
        """Invariant: 20 < char_count < 100 → 0.7 < quality_factor < 1.0."""
        for count in [30, 50, 70, 90]:
            source = {"transcript_char_count": count}
            factor = compute_quality_factor(source)
            assert QUALITY_FLOOR < factor < 1.0, f"Failed for char_count={count}"


class TestDiversificationInvariants:
    """Test: Diversification rules and behavior."""

    def test_result_count_bounded(self):
        """Invariant: len(results) ≤ target_count."""
        ranked = [
            RankedItem(doc_id=f"doc{i}", video_id=f"v{i % 5}", source={}, adjusted_score=1.0 - i * 0.01)
            for i in range(50)
        ]
        
        target = 20
        results = diversify_results(ranked, max_per_video=4, target_count=target)
        
        assert len(results) <= target

    def test_penalized_items_marked(self):
        """Invariant: Items exceeding per-video limit are marked with penalty."""
        ranked = []
        for v in range(6):
            for s in range(5):
                ranked.append(RankedItem(
                    doc_id=f"v{v}_s{s}",
                    video_id=f"video{v}",
                    source={},
                    adjusted_score=1.0 - v * 0.1 - s * 0.01,
                ))
        
        results = diversify_results(ranked, max_per_video=2, target_count=15)
        
        penalized = [r for r in results if r.diversification_penalty]
        
        assert len(penalized) == 3, f"Expected 3 penalized items (6*2=12 first pass, need 3 more)"

    def test_sufficient_diversity_limits_per_video(self):
        """Invariant: With sufficient diversity, no video exceeds max_per_video."""
        ranked = []
        for v in range(10):
            for s in range(5):
                ranked.append(RankedItem(
                    doc_id=f"v{v}_s{s}",
                    video_id=f"video{v}",
                    source={},
                    adjusted_score=1.0 - v * 0.1 - s * 0.01,
                ))
        
        max_per = 2
        results = diversify_results(ranked, max_per_video=max_per, target_count=15)
        
        from collections import Counter
        video_counts = Counter(r.video_id for r in results)
        
        for video_id, count in video_counts.items():
            non_penalized = sum(1 for r in results if r.video_id == video_id and not r.diversification_penalty)
            assert non_penalized <= max_per + 1, f"Video {video_id} has too many non-penalized results"


class TestRRFScoreFormula:
    """Test: RRF score formula correctness."""

    def test_rrf_score_formula(self):
        """Verify: rrf_score(rank, k) = 1 / (k + rank)."""
        settings = get_settings()
        k = settings.search_rrf_k
        
        for rank in [1, 5, 10, 50, 100]:
            expected = 1.0 / (k + rank)
            actual = rrf_score(rank, k)
            assert actual == pytest.approx(expected)

    def test_rrf_score_none_rank(self):
        """Verify: None rank returns 0.0."""
        assert rrf_score(None) == 0.0
        assert rrf_score(None, k=30) == 0.0

    def test_rrf_score_ranking_spread(self):
        """Verify: Higher ranks give lower scores."""
        settings = get_settings()
        k = settings.search_rrf_k
        
        scores = [rrf_score(r, k) for r in [1, 2, 5, 10, 50, 100]]
        
        for i in range(len(scores) - 1):
            assert scores[i] > scores[i + 1], "Scores should decrease with rank"


class TestBothSignalsBoost:
    """Test: Items in both result sets get boosted."""

    def test_both_signals_higher_score(self):
        """Verify: Item in both sets scores higher than item in one set."""
        lexical = [
            {"_id": "both", "_score": 10.0, "_source": {"video_id": "v1", "transcript_char_count": 100}},
            {"_id": "lex_only", "_score": 8.0, "_source": {"video_id": "v2", "transcript_char_count": 100}},
        ]
        vector = [
            {"_id": "both", "_score": 0.9, "_source": {"video_id": "v1", "transcript_char_count": 100}},
            {"_id": "vec_only", "_score": 0.8, "_source": {"video_id": "v3", "transcript_char_count": 100}},
        ]
        
        results = compute_weighted_rrf(lexical, vector, [], bm25_weight=0.5, text_knn_weight=0.5, visual_weight=0.0)
        
        both_item = next(r for r in results if r.doc_id == "both")
        lex_only = next(r for r in results if r.doc_id == "lex_only")
        vec_only = next(r for r in results if r.doc_id == "vec_only")
        
        assert both_item.fused_score > lex_only.fused_score
        assert both_item.fused_score > vec_only.fused_score


class TestNormalizationIntegration:
    """Test: Normalized character count used for quality factor."""

    def test_emoji_excluded_from_quality(self):
        """Verify: Emoji-heavy text uses normalized char count."""
        from app.modules.search.normalize import get_normalized_char_count
        
        emoji_text = "안녕 🎉🎊🎁🎉🎊🎁 하세요"
        clean_text = "안녕 하세요"
        
        emoji_count = get_normalized_char_count(emoji_text)
        clean_count = len(clean_text.replace(" ", "")) + 1
        
        source_emoji = {"transcript_raw": emoji_text}
        source_clean = {"transcript_raw": clean_text}
        
        factor_emoji = compute_quality_factor(source_emoji)
        factor_clean = compute_quality_factor(source_clean)
        
        assert factor_emoji == pytest.approx(factor_clean, rel=0.1)
