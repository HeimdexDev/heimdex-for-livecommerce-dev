import pytest
from app.modules.search.fusion import (
    rrf_score,
    compute_weighted_rrf,
    compute_quality_factor,
    diversify_results,
    RankedItem,
    MIN_TRANSCRIPT_CHARS,
    GOOD_TRANSCRIPT_CHARS,
    QUALITY_FLOOR,
)


class TestRRFScore:
    def test_rank_1_default_k(self):
        score = rrf_score(1, k=60)
        assert score == pytest.approx(1 / 61)
    
    def test_rank_none_returns_zero(self):
        assert rrf_score(None) == 0.0
    
    def test_higher_rank_lower_score(self):
        assert rrf_score(1) > rrf_score(10)
        assert rrf_score(10) > rrf_score(100)
    
    def test_custom_k_value(self):
        score = rrf_score(1, k=100)
        assert score == pytest.approx(1 / 101)


class TestComputeWeightedRRF:
    def test_alpha_zero_lexical_only(self):
        lexical = [
            {"_id": "doc1", "_score": 10.0, "_source": {"video_id": "v1"}},
            {"_id": "doc2", "_score": 5.0, "_source": {"video_id": "v2"}},
        ]
        vector = [
            {"_id": "doc2", "_score": 0.9, "_source": {"video_id": "v2"}},
            {"_id": "doc3", "_score": 0.8, "_source": {"video_id": "v3"}},
        ]
        
        results = compute_weighted_rrf(lexical, vector, alpha=0.0)
        
        assert results[0].doc_id == "doc1"
        assert results[0].lexical_rank == 1
        assert results[0].vector_rank is None
    
    def test_alpha_one_vector_only(self):
        lexical = [
            {"_id": "doc1", "_score": 10.0, "_source": {"video_id": "v1"}},
        ]
        vector = [
            {"_id": "doc2", "_score": 0.9, "_source": {"video_id": "v2"}},
            {"_id": "doc1", "_score": 0.5, "_source": {"video_id": "v1"}},
        ]
        
        results = compute_weighted_rrf(lexical, vector, alpha=1.0)
        
        assert results[0].doc_id == "doc2"
        assert results[0].vector_rank == 1
    
    def test_alpha_balanced_merges_results(self):
        lexical = [
            {"_id": "doc1", "_score": 10.0, "_source": {"video_id": "v1"}},
            {"_id": "doc2", "_score": 5.0, "_source": {"video_id": "v2"}},
        ]
        vector = [
            {"_id": "doc2", "_score": 0.9, "_source": {"video_id": "v2"}},
            {"_id": "doc1", "_score": 0.5, "_source": {"video_id": "v1"}},
        ]
        
        results = compute_weighted_rrf(lexical, vector, alpha=0.5)
        
        doc2 = next(r for r in results if r.doc_id == "doc2")
        assert doc2.lexical_rank == 2
        assert doc2.vector_rank == 1
        assert doc2.fused_score > 0
    
    def test_empty_results(self):
        results = compute_weighted_rrf([], [], alpha=0.5)
        assert results == []
    
    def test_deterministic_ordering(self):
        lexical = [{"_id": f"doc{i}", "_score": 10 - i, "_source": {"video_id": f"v{i}"}} for i in range(10)]
        vector = [{"_id": f"doc{i}", "_score": 1 - i * 0.1, "_source": {"video_id": f"v{i}"}} for i in range(10)]
        
        results1 = compute_weighted_rrf(lexical, vector, alpha=0.5)
        results2 = compute_weighted_rrf(lexical, vector, alpha=0.5)
        
        assert [r.doc_id for r in results1] == [r.doc_id for r in results2]


class TestDiversifyResults:
    def test_limits_per_video(self):
        items = [
            RankedItem(doc_id="seg1", video_id="v1", source={}, fused_score=1.0, adjusted_score=1.0),
            RankedItem(doc_id="seg2", video_id="v1", source={}, fused_score=0.9, adjusted_score=0.9),
            RankedItem(doc_id="seg3", video_id="v1", source={}, fused_score=0.8, adjusted_score=0.8),
            RankedItem(doc_id="seg4", video_id="v2", source={}, fused_score=0.7, adjusted_score=0.7),
            RankedItem(doc_id="seg5", video_id="v2", source={}, fused_score=0.6, adjusted_score=0.6),
            RankedItem(doc_id="seg6", video_id="v3", source={}, fused_score=0.5, adjusted_score=0.5),
            RankedItem(doc_id="seg7", video_id="v3", source={}, fused_score=0.4, adjusted_score=0.4),
            RankedItem(doc_id="seg8", video_id="v4", source={}, fused_score=0.3, adjusted_score=0.3),
        ]
        
        result = diversify_results(items, max_per_video=2, target_count=4)
        
        v1_count = sum(1 for r in result if r.video_id == "v1")
        assert v1_count == 2
        assert len(result) == 4
    
    def test_fills_target_count(self):
        items = [
            RankedItem(doc_id="seg1", video_id="v1", source={}, fused_score=1.0, adjusted_score=1.0),
            RankedItem(doc_id="seg2", video_id="v2", source={}, fused_score=0.9, adjusted_score=0.9),
            RankedItem(doc_id="seg3", video_id="v3", source={}, fused_score=0.8, adjusted_score=0.8),
        ]
        
        result = diversify_results(items, max_per_video=2, target_count=3)
        
        assert len(result) == 3
    
    def test_relaxes_cap_if_needed(self):
        items = [
            RankedItem(doc_id="seg1", video_id="v1", source={}, fused_score=1.0, adjusted_score=1.0),
            RankedItem(doc_id="seg2", video_id="v1", source={}, fused_score=0.9, adjusted_score=0.9),
            RankedItem(doc_id="seg3", video_id="v1", source={}, fused_score=0.8, adjusted_score=0.8),
        ]
        
        result = diversify_results(items, max_per_video=2, target_count=3)
        
        assert len(result) == 3
    
    def test_preserves_order_by_score(self):
        items = [
            RankedItem(doc_id="seg1", video_id="v1", source={}, fused_score=1.0, adjusted_score=1.0),
            RankedItem(doc_id="seg2", video_id="v2", source={}, fused_score=0.9, adjusted_score=0.9),
            RankedItem(doc_id="seg3", video_id="v3", source={}, fused_score=0.8, adjusted_score=0.8),
        ]
        
        result = diversify_results(items, max_per_video=2, target_count=3)
        
        assert result[0].doc_id == "seg1"
        assert result[1].doc_id == "seg2"
        assert result[2].doc_id == "seg3"
    
    def test_tracks_diversification_penalty(self):
        items = [
            RankedItem(doc_id="seg1", video_id="v1", source={}, fused_score=1.0, adjusted_score=1.0),
            RankedItem(doc_id="seg2", video_id="v1", source={}, fused_score=0.9, adjusted_score=0.9),
            RankedItem(doc_id="seg3", video_id="v1", source={}, fused_score=0.8, adjusted_score=0.8),
            RankedItem(doc_id="seg4", video_id="v1", source={}, fused_score=0.7, adjusted_score=0.7),
            RankedItem(doc_id="seg5", video_id="v2", source={}, fused_score=0.6, adjusted_score=0.6),
        ]
        
        result = diversify_results(items, max_per_video=2, target_count=4)
        
        assert len(result) == 4
        penalized = [r for r in result if r.diversification_penalty]
        assert len(penalized) == 1
        assert penalized[0].doc_id == "seg3"
    
    def test_single_video_dominates_when_best(self):
        items = [
            RankedItem(doc_id=f"seg{i}", video_id="v1", source={}, fused_score=1.0 - i * 0.01, adjusted_score=1.0 - i * 0.01)
            for i in range(10)
        ]
        
        result = diversify_results(items, max_per_video=4, target_count=10)
        
        assert len(result) == 10
        assert all(r.video_id == "v1" for r in result)


class TestQualityFactor:
    def test_empty_transcript_gets_floor(self):
        source = {"transcript_raw": ""}
        assert compute_quality_factor(source) == QUALITY_FLOOR
    
    def test_short_transcript_gets_floor(self):
        source = {"transcript_raw": "a" * MIN_TRANSCRIPT_CHARS}
        assert compute_quality_factor(source) == QUALITY_FLOOR
    
    def test_good_transcript_gets_full_score(self):
        source = {"transcript_raw": "a" * GOOD_TRANSCRIPT_CHARS}
        assert compute_quality_factor(source) == 1.0
    
    def test_long_transcript_capped_at_one(self):
        source = {"transcript_raw": "a" * 1000}
        assert compute_quality_factor(source) == 1.0
    
    def test_medium_transcript_interpolated(self):
        mid_length = (MIN_TRANSCRIPT_CHARS + GOOD_TRANSCRIPT_CHARS) // 2
        source = {"transcript_raw": "a" * mid_length}
        factor = compute_quality_factor(source)
        assert QUALITY_FLOOR < factor < 1.0
    
    def test_precomputed_char_count_used(self):
        source = {"transcript_char_count": 200, "transcript_raw": "short"}
        assert compute_quality_factor(source) == 1.0
    
    def test_fallback_to_transcript_norm(self):
        source = {"transcript_norm": "a" * GOOD_TRANSCRIPT_CHARS}
        assert compute_quality_factor(source) == 1.0


class TestRRFContributions:
    def test_contributions_tracked(self):
        lexical = [{"_id": "doc1", "_score": 10.0, "_source": {"video_id": "v1"}}]
        vector = [{"_id": "doc1", "_score": 0.9, "_source": {"video_id": "v1"}}]
        
        results = compute_weighted_rrf(lexical, vector, alpha=0.5)
        
        assert results[0].lexical_contribution > 0
        assert results[0].vector_contribution > 0
        assert results[0].fused_score == pytest.approx(
            results[0].lexical_contribution + results[0].vector_contribution
        )
    
    def test_alpha_zero_no_vector_contribution(self):
        lexical = [{"_id": "doc1", "_score": 10.0, "_source": {"video_id": "v1"}}]
        vector = [{"_id": "doc1", "_score": 0.9, "_source": {"video_id": "v1"}}]
        
        results = compute_weighted_rrf(lexical, vector, alpha=0.0)
        
        assert results[0].lexical_contribution > 0
        assert results[0].vector_contribution == 0
    
    def test_alpha_one_no_lexical_contribution(self):
        lexical = [{"_id": "doc1", "_score": 10.0, "_source": {"video_id": "v1"}}]
        vector = [{"_id": "doc1", "_score": 0.9, "_source": {"video_id": "v1"}}]
        
        results = compute_weighted_rrf(lexical, vector, alpha=1.0)
        
        assert results[0].lexical_contribution == 0
        assert results[0].vector_contribution > 0
    
    def test_quality_factor_affects_adjusted_score(self):
        lexical = [
            {"_id": "doc1", "_score": 10.0, "_source": {"video_id": "v1", "transcript_raw": "a" * 200}},
            {"_id": "doc2", "_score": 9.0, "_source": {"video_id": "v2", "transcript_raw": "b" * 10}},
        ]
        
        results = compute_weighted_rrf(lexical, [], alpha=0.0)
        
        doc1 = next(r for r in results if r.doc_id == "doc1")
        doc2 = next(r for r in results if r.doc_id == "doc2")
        
        assert doc1.quality_factor == 1.0
        assert doc2.quality_factor == QUALITY_FLOOR
        assert doc1.adjusted_score > doc2.adjusted_score
