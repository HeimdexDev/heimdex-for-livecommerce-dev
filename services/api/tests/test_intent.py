"""Tests for query intent classification."""
import pytest

from app.modules.search.intent import SearchIntent, classify_intent


class TestClassifyIntent:
    """Test rule-based intent classification for Korean livecommerce queries."""

    # ---------------------------------------------------------------
    # Metadata intent (prices, discounts, dates)
    # ---------------------------------------------------------------
    @pytest.mark.parametrize("query", [
        "3만원 이하 립스틱",
        "할인 세일 화장품",
        "특가 상품",
        "쿠폰 사용",
        "무료배송 화장품",
        "5천원짜리",
        "2026-03 신상",
        "오늘 라이브",
        "이번 주 방송",
        "가격 비교",
        "최저가 세럼",
        "3개 세트",
    ])
    def test_metadata_intent(self, query: str) -> None:
        result = classify_intent(query)
        assert result.intent_type == "metadata"
        assert result.alpha == 0.0, "metadata should be pure BM25"
        assert result.bm25_weight == 1.0
        assert result.visual_weight == 0.0
        assert len(result.matched_patterns) > 0

    # ---------------------------------------------------------------
    # Visual intent (colors, shapes, appearance)
    # ---------------------------------------------------------------
    @pytest.mark.parametrize("query", [
        "빨간 립스틱",
        "분홍색 블러셔",
        "핑크 톤",
        "검정 아이라이너",
        "베이지 파운데이션",
        "꽃무늬 원피스",
        "줄무늬 니트",
        "미니 사이즈",
        "착용 모습",
        "입고 있는 옷",
        "보여주세요",
        "어떤 색",
        "골드 팔찌",
    ])
    def test_visual_intent(self, query: str) -> None:
        result = classify_intent(query)
        assert result.intent_type == "visual"
        assert result.visual_weight > 0.0, "visual intent should have visual kNN weight"
        assert result.alpha > 0.5, "visual should lean semantic"
        assert len(result.matched_patterns) > 0

    # ---------------------------------------------------------------
    # Factual intent (ingredients, effects, how-to)
    # ---------------------------------------------------------------
    @pytest.mark.parametrize("query", [
        "히알루론산 성분",
        "레티놀 효과",
        "비타민C 세럼 효능",
        "사용법 알려주세요",
        "바르는 순서",
        "SPF50 자외선 차단",
        "콜라겐 함량",
        "나이아신아마이드 추출물",
    ])
    def test_factual_intent(self, query: str) -> None:
        result = classify_intent(query)
        assert result.intent_type == "factual"
        assert result.bm25_weight > result.text_knn_weight, "factual should be BM25-heavy"
        assert len(result.matched_patterns) > 0

    # ---------------------------------------------------------------
    # General intent (broad, no specific patterns)
    # ---------------------------------------------------------------
    @pytest.mark.parametrize("query", [
        "화장품",
        "스킨케어",
        "뷰티 방송",
        "라이브커머스",
        "좋아요",
        "인기 상품",
    ])
    def test_general_intent(self, query: str) -> None:
        result = classify_intent(query)
        assert result.intent_type == "general"
        assert result.alpha > 0.5, "general should lean semantic"
        assert result.matched_patterns == ()

    # ---------------------------------------------------------------
    # Edge cases
    # ---------------------------------------------------------------
    def test_empty_query(self) -> None:
        result = classify_intent("")
        assert result.intent_type == "general"

    def test_whitespace_query(self) -> None:
        result = classify_intent("   ")
        assert result.intent_type == "general"

    def test_metadata_takes_priority(self) -> None:
        """Metadata intent should win over visual when both match."""
        # "할인 빨간 립스틱" has both metadata (할인) and visual (빨간) patterns
        result = classify_intent("할인 빨간 립스틱")
        assert result.intent_type == "metadata"

    def test_factual_over_visual_when_equal(self) -> None:
        """Factual should win over visual when match count is equal."""
        result = classify_intent("성분 좋은 크림")
        assert result.intent_type == "factual"

    def test_visual_wins_when_more_matches(self) -> None:
        """Visual should win over factual when it has more pattern matches."""
        # Multiple visual patterns but only one factual
        result = classify_intent("빨간 줄무늬 큰 사이즈 추천")
        # "빨간" (color) + "줄무늬" (pattern) + "큰" (size) = 3 visual
        # "추천" (comparison) = 1 factual
        assert result.intent_type == "visual"


class TestSearchIntentProperties:
    """Test SearchIntent dataclass behavior."""

    def test_intent_is_frozen(self) -> None:
        intent = classify_intent("테스트")
        with pytest.raises(AttributeError):
            intent.alpha = 0.5  # type: ignore[misc]

    def test_weights_sum_to_one(self) -> None:
        """All weight configurations should sum to approximately 1.0."""
        for query in ["할인", "빨간 립", "성분 효과", "화장품"]:
            intent = classify_intent(query)
            total = intent.visual_weight + intent.text_knn_weight + intent.bm25_weight
            assert abs(total - 1.0) < 0.01, (
                f"Weights for intent '{intent.intent_type}' sum to {total}, "
                f"expected ~1.0 (visual={intent.visual_weight}, "
                f"text_knn={intent.text_knn_weight}, bm25={intent.bm25_weight})"
            )

    def test_alpha_range(self) -> None:
        """Alpha should always be between 0.0 and 1.0."""
        for query in ["할인", "빨간", "성분", "화장품", ""]:
            intent = classify_intent(query)
            assert 0.0 <= intent.alpha <= 1.0
