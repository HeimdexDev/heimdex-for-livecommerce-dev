"""
Search quality evaluation tests with golden query sets.

These tests verify search quality using predefined Korean queries
and expected results. Used for regression testing and tuning.

Run with: pytest tests/test_search_quality.py -v

NOTE: These tests require:
1. Running OpenSearch instance with seeded data
2. Expected segment_ids must exist in the index

Skip with: pytest tests/test_search_quality.py -v -m "not quality"
"""
import pytest
import pytest_asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4, UUID

from app.modules.search.schemas import SearchFilters
from app.modules.search.fusion import compute_weighted_rrf, diversify_results, RankedItem


# =============================================================================
# GOLDEN QUERY SET - 10 Korean queries for quality evaluation
# =============================================================================
# 
# These queries represent typical user search patterns for Korean video content.
# Expected behavior is documented for each query type.
#
# NOTE: segment_ids are placeholders - update with actual IDs from your test data
# =============================================================================

@dataclass
class GoldenQuery:
    """A query with expected results for quality testing."""
    query: str
    description: str
    category: str
    # Expected segment_ids that SHOULD appear in top 20 (order doesn't matter)
    expected_segment_ids: list[str]
    # Alpha values to test: 0=lexical, 0.5=hybrid, 1=semantic
    test_alphas: list[float] | None = None
    
    def __post_init__(self):
        if self.test_alphas is None:
            self.test_alphas = [0.0, 0.5, 1.0]


# Golden query set - 10 representative Korean queries
GOLDEN_QUERIES = [
    # Category 1: Product Announcements
    GoldenQuery(
        query="신제품 출시",
        description="New product launch announcements",
        category="product",
        expected_segment_ids=[],  # Populate with actual segment IDs from test data
    ),
    GoldenQuery(
        query="할인 행사",
        description="Discount/sale event announcements",
        category="product",
        expected_segment_ids=[],
    ),
    GoldenQuery(
        query="무료 배송",
        description="Free shipping mentions",
        category="product",
        expected_segment_ids=[],
    ),
    
    # Category 2: Technical Terms (Mixed Korean/English)
    GoldenQuery(
        query="API 연동",
        description="API integration discussions",
        category="technical",
        expected_segment_ids=[],
    ),
    GoldenQuery(
        query="SDK 설치 방법",
        description="SDK installation tutorials",
        category="technical",
        expected_segment_ids=[],
    ),
    
    # Category 3: Short Queries (Phrase Matching)
    GoldenQuery(
        query="세일 기간",
        description="Sale period - exact phrase should boost",
        category="short_phrase",
        expected_segment_ids=[],
    ),
    GoldenQuery(
        query="사용 방법",
        description="Usage instructions",
        category="short_phrase",
        expected_segment_ids=[],
    ),
    GoldenQuery(
        query="주문 취소",
        description="Order cancellation",
        category="short_phrase",
        expected_segment_ids=[],
    ),
    
    # Category 4: Long-tail Queries
    GoldenQuery(
        query="이번 주 금요일까지 진행하는 특별 할인",
        description="Special discount until Friday this week",
        category="long_tail",
        expected_segment_ids=[],
    ),
    GoldenQuery(
        query="구매 후 7일 이내 반품 가능한지",
        description="Whether returns are possible within 7 days of purchase",
        category="long_tail",
        expected_segment_ids=[],
    ),
]


# =============================================================================
# Unit Tests (Mocked) - Test fusion and diversification logic
# =============================================================================

class TestRRFQualitySignals:
    """Test that RRF fusion produces expected quality signals."""

    def test_alpha_0_prioritizes_lexical(self):
        """alpha=0 should give 100% weight to lexical results."""
        lexical_hits = [
            {"_id": "lex1", "_score": 10.0, "_source": {"video_id": "v1", "transcript_char_count": 100}},
            {"_id": "lex2", "_score": 8.0, "_source": {"video_id": "v2", "transcript_char_count": 100}},
        ]
        vector_hits = [
            {"_id": "vec1", "_score": 0.95, "_source": {"video_id": "v3", "transcript_char_count": 100}},
            {"_id": "vec2", "_score": 0.90, "_source": {"video_id": "v4", "transcript_char_count": 100}},
        ]
        
        ranked = compute_weighted_rrf(lexical_hits, vector_hits, alpha=0.0)
        
        # Top results should be lexical (lex1, lex2)
        assert ranked[0].doc_id == "lex1"
        assert ranked[1].doc_id == "lex2"
        
        # Vector contribution should be 0 for alpha=0
        assert ranked[0].vector_contribution == 0.0

    def test_alpha_1_prioritizes_vector(self):
        """alpha=1 should give 100% weight to vector results."""
        lexical_hits = [
            {"_id": "lex1", "_score": 10.0, "_source": {"video_id": "v1", "transcript_char_count": 100}},
        ]
        vector_hits = [
            {"_id": "vec1", "_score": 0.95, "_source": {"video_id": "v2", "transcript_char_count": 100}},
        ]
        
        ranked = compute_weighted_rrf(lexical_hits, vector_hits, alpha=1.0)
        
        # Top result should be vector
        assert ranked[0].doc_id == "vec1"
        
        # Lexical contribution should be 0 for alpha=1
        assert ranked[0].lexical_contribution == 0.0

    def test_alpha_05_balances_both(self):
        """alpha=0.5 should balance lexical and vector equally."""
        # Create results where same doc appears in both
        lexical_hits = [
            {"_id": "both", "_score": 10.0, "_source": {"video_id": "v1", "transcript_char_count": 100}},
        ]
        vector_hits = [
            {"_id": "both", "_score": 0.95, "_source": {"video_id": "v1", "transcript_char_count": 100}},
        ]
        
        ranked = compute_weighted_rrf(lexical_hits, vector_hits, alpha=0.5)
        
        # Document appearing in both should have contributions from each
        assert ranked[0].lexical_contribution > 0
        assert ranked[0].vector_contribution > 0
        # At alpha=0.5, contributions should be approximately equal (same rank)
        assert abs(ranked[0].lexical_contribution - ranked[0].vector_contribution) < 0.01

    def test_quality_factor_penalizes_short_transcripts(self):
        """Short transcripts should have lower quality factor."""
        hits = [
            {"_id": "long", "_score": 10.0, "_source": {"video_id": "v1", "transcript_char_count": 200}},
            {"_id": "short", "_score": 10.0, "_source": {"video_id": "v2", "transcript_char_count": 10}},
        ]
        
        ranked = compute_weighted_rrf(hits, [], alpha=0.0)
        
        long_item = next(r for r in ranked if r.doc_id == "long")
        short_item = next(r for r in ranked if r.doc_id == "short")
        
        assert long_item.quality_factor == 1.0  # Full quality
        assert short_item.quality_factor < 1.0  # Penalized


class TestDiversificationQuality:
    """Test that diversification preserves quality while preventing video dominance."""

    def test_diversification_limits_per_video(self):
        """Results from a single video should be limited when sufficient diversity exists."""
        # Create scenario where:
        # - Many videos exist (>= target_count // max_per_video)
        # - One video dominates rankings
        # - Diversification should kick in
        ranked = []
        # Video 1 has 10 high-scored results
        for i in range(10):
            ranked.append(RankedItem(
                doc_id=f"v1_s{i}", video_id="video1", source={},
                adjusted_score=1.0 - i * 0.01
            ))
        # Videos 2-6 have 2 results each (total 5 videos with results)
        for v in range(2, 7):
            for s in range(2):
                ranked.append(RankedItem(
                    doc_id=f"v{v}_s{s}", video_id=f"video{v}", source={},
                    adjusted_score=0.5 - v * 0.05 - s * 0.01
                ))
        
        # With max_per_video=2 and 5+ unique videos, diversification should apply
        diversified = diversify_results(ranked, max_per_video=2, target_count=10)
        
        # Video1 should be limited, not dominate all 10 slots
        video1_results = [r for r in diversified if r.video_id == "video1"]
        assert len(video1_results) <= 4  # Should be limited (not all 10)
        
        # Multiple videos should be represented
        unique_videos = len(set(r.video_id for r in diversified))
        assert unique_videos >= 3  # Diversity achieved

    def test_diversification_preserves_ranking(self):
        """Higher ranked items should still appear first after diversification."""
        ranked = [
            RankedItem(doc_id="best1", video_id="v1", source={}, adjusted_score=1.0),
            RankedItem(doc_id="best2", video_id="v2", source={}, adjusted_score=0.9),
            RankedItem(doc_id="v1_second", video_id="v1", source={}, adjusted_score=0.8),
            RankedItem(doc_id="v2_second", video_id="v2", source={}, adjusted_score=0.7),
        ]
        
        diversified = diversify_results(ranked, max_per_video=2, target_count=4)
        
        # Original ranking should be preserved
        assert diversified[0].doc_id == "best1"
        assert diversified[1].doc_id == "best2"

    def test_diversification_marks_penalty(self):
        """Items exceeding per-video limit should be marked with penalty when added back."""
        # Create scenario where:
        # - Many unique videos to trigger diversification
        # - Not enough non-penalized items to fill target_count
        # - Penalized items must be added back to reach target
        ranked = []
        # 6 videos with 3 results each
        for v in range(6):
            for s in range(3):
                ranked.append(RankedItem(
                    doc_id=f"v{v}_s{s}", video_id=f"video{v}", source={},
                    adjusted_score=1.0 - v * 0.1 - s * 0.01
                ))
        
        # max_per_video=2, target_count=15
        # First pass: 6 videos * 2 items = 12 items (non-penalized)
        # Need 3 more items -> pull from penalized pool
        diversified = diversify_results(ranked, max_per_video=2, target_count=15)
        
        # Some items should have diversification penalty (added back to fill target)
        penalized_items = [r for r in diversified if r.diversification_penalty]
        
        # With 6 videos * 2 max = 12 slots in first pass, need 3 penalized to reach 15
        assert len(penalized_items) == 3, f"Expected 3 penalized items, got {len(penalized_items)}"
        
        # Total should be target_count
        assert len(diversified) == 15


# =============================================================================
# Integration Tests (Require Live OpenSearch)
# =============================================================================

@pytest.mark.quality
@pytest.mark.integration
class TestGoldenQueryQuality:
    """
    Integration tests using golden query set.
    
    These tests verify that expected segments appear in top 20 results.
    Run after seeding test data with known segment IDs.
    """

    @pytest_asyncio.fixture
    async def search_service(self):
        """Create SearchService with live connections."""
        from app.modules.search.client import OpenSearchClient
        from app.modules.search.service import SearchService
        
        # This requires actual DB session - skip if not available
        pytest.skip("Requires live database session - run with integration setup")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("golden", GOLDEN_QUERIES, ids=lambda g: g.query[:20])
    async def test_golden_query_precision(self, search_service, golden: GoldenQuery):
        """
        Test that expected segments appear in top 20 for each golden query.
        
        This test verifies search quality across different alpha values.
        """
        if not golden.expected_segment_ids:
            pytest.skip(f"No expected segment_ids defined for query: {golden.query}")
        
        org_id = uuid4()  # Should match test data
        
        for alpha in golden.test_alphas or []:
            response = await search_service.search(
                query=golden.query,
                org_id=org_id,
                alpha=alpha,
                filters=SearchFilters(),
            )
            
            result_ids = {r.segment_id for r in response.results[:20]}
            expected_ids = set(golden.expected_segment_ids)
            
            # Calculate precision: how many expected IDs appear in top 20
            hits = result_ids & expected_ids
            precision = len(hits) / len(expected_ids) if expected_ids else 1.0
            
            # Report for debugging
            print(f"\nQuery: {golden.query} (alpha={alpha})")
            print(f"  Precision: {precision:.2%} ({len(hits)}/{len(expected_ids)})")
            print(f"  Missing: {expected_ids - result_ids}")
            
            # Soft assertion - warn instead of fail during tuning
            if precision < 0.5:
                pytest.fail(
                    f"Low precision ({precision:.2%}) for '{golden.query}' at alpha={alpha}. "
                    f"Expected: {expected_ids}, Got: {result_ids}"
                )


# =============================================================================
# Property-Based Quality Tests (Mocked, using YAML fixture)
# =============================================================================

def load_golden_queries_yaml():
    """Load golden queries from YAML fixture."""
    import yaml
    from pathlib import Path
    
    fixture_path = Path(__file__).parent / "fixtures" / "golden_queries.yaml"
    if not fixture_path.exists():
        return {"queries": [], "config": {}}
    
    with open(fixture_path) as f:
        return yaml.safe_load(f)


class TestPropertyBasedQuality:
    """
    Property-based quality tests using YAML fixture.
    
    These tests verify search behavior using property assertions rather than
    brittle segment IDs. Tests run with mocked search results.
    """

    def test_diversification_max_same_video(self):
        """Verify: With sufficient video diversity, per-video limit is respected."""
        fixture = load_golden_queries_yaml()
        config = fixture.get("config", {})
        if not isinstance(config, dict):
            config = {}
        max_per_video = config.get("default_max_per_video", 4)
        
        ranked = []
        for v in range(10):
            for s in range(6):
                ranked.append(RankedItem(
                    doc_id=f"v{v}_s{s}",
                    video_id=f"video{v}",
                    source={"transcript_char_count": 100},
                    adjusted_score=1.0 - v * 0.05 - s * 0.01,
                ))
        
        diversified = diversify_results(ranked, max_per_video=max_per_video, target_count=20)
        
        from collections import Counter
        video_counts = Counter(r.video_id for r in diversified)
        
        for video_id, count in video_counts.items():
            non_penalized = sum(1 for r in diversified 
                               if r.video_id == video_id and not r.diversification_penalty)
            assert non_penalized <= max_per_video

    def test_quality_floor_respected(self):
        """Verify: Quality factor never drops below floor."""
        fixture = load_golden_queries_yaml()
        config = fixture.get("config", {})
        if not isinstance(config, dict):
            config = {}
        quality_floor = config.get("quality_floor", 0.7)
        
        from app.modules.search.fusion import compute_quality_factor
        
        test_sources = [
            {"transcript_char_count": 0},
            {"transcript_char_count": 5},
            {"transcript_raw": ""},
            {"transcript_raw": "short"},
        ]
        
        for source in test_sources:
            factor = compute_quality_factor(source)
            assert factor >= quality_floor

    def test_alpha_extremes_behavior(self):
        """Verify: Alpha=0 uses lexical only, alpha=1 uses vector only."""
        lexical = [{"_id": "lex", "_score": 10.0, "_source": {"video_id": "v1"}}]
        vector = [{"_id": "vec", "_score": 0.9, "_source": {"video_id": "v2"}}]
        
        results_lex = compute_weighted_rrf(lexical, vector, alpha=0.0)
        assert results_lex[0].doc_id == "lex"
        assert results_lex[0].vector_contribution == 0.0
        
        results_vec = compute_weighted_rrf(lexical, vector, alpha=1.0)
        assert results_vec[0].doc_id == "vec"
        assert results_vec[0].lexical_contribution == 0.0

    def test_short_query_categories(self):
        """Verify: Short queries (≤3 words) are correctly categorized."""
        fixture = load_golden_queries_yaml()
        queries = fixture.get("queries", [])
        
        short_phrase_queries = [q for q in queries if q.get("category") == "short_phrase"]
        
        for query_def in short_phrase_queries:
            query = query_def.get("query", "")
            word_count = len(query.split())
            assert word_count <= 3, f"Short phrase query '{query}' has {word_count} words"

    def test_long_tail_categories(self):
        """Verify: Long-tail queries have more words."""
        fixture = load_golden_queries_yaml()
        queries = fixture.get("queries", [])
        
        long_tail_queries = [q for q in queries if q.get("category") == "long_tail"]
        
        for query_def in long_tail_queries:
            query = query_def.get("query", "")
            word_count = len(query.split())
            assert word_count > 3, f"Long-tail query '{query}' has only {word_count} words"


# =============================================================================
# RRF Tuning Tests
# =============================================================================

class TestRRFTuning:
    """Tests for experimenting with RRF parameter tuning."""

    @pytest.mark.parametrize("k", [30, 60, 100])
    def test_rrf_k_impact(self, k):
        """
        Test impact of RRF k parameter on ranking.
        
        Lower k gives more weight to top-ranked results.
        Higher k smooths out rank differences.
        """
        from app.modules.search.fusion import rrf_score
        
        # Score difference between rank 1 and rank 10
        score_1 = rrf_score(1, k)
        score_10 = rrf_score(10, k)
        
        ratio = score_1 / score_10
        
        print(f"\nRRF k={k}: rank1={score_1:.4f}, rank10={score_10:.4f}, ratio={ratio:.2f}x")
        
        # Verify k impacts ranking spread
        # Lower k should give higher ratio (more spread)
        # Formula: 1/(k+1) / 1/(k+10) = (k+10)/(k+1)
        # k=30: 40/31 = 1.29, k=60: 70/61 = 1.15, k=100: 110/101 = 1.09
        if k == 30:
            assert ratio > 1.25  # More aggressive ranking
        elif k == 100:
            assert ratio < 1.15  # More smoothed

    def test_diversification_cap_tuning(self):
        """Test different max_per_video values impact on result diversity."""
        # 20 results from 5 videos (4 each)
        ranked = []
        for v in range(5):
            for s in range(4):
                ranked.append(RankedItem(
                    doc_id=f"v{v}_s{s}",
                    video_id=f"video{v}",
                    source={},
                    adjusted_score=1.0 - (v * 0.1 + s * 0.01),
                ))
        
        for max_per in [2, 4, 6]:
            diversified = diversify_results(ranked, max_per_video=max_per, target_count=20)
            
            unique_videos = len(set(r.video_id for r in diversified))
            penalized = sum(1 for r in diversified if r.diversification_penalty)
            
            print(f"\nmax_per_video={max_per}: "
                  f"unique_videos={unique_videos}, "
                  f"penalized={penalized}, "
                  f"total={len(diversified)}")
            
            # More restrictive cap = more unique videos
            if max_per == 2:
                assert unique_videos == 5  # Must have results from all videos
