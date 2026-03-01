"""
Query intent classification for Korean livecommerce search.

Classifies user queries into intent categories and returns optimal search
parameters (alpha, boost weights) for each. This allows the semantic search
mode to intelligently blend BM25 and kNN signals based on query type.

Intent categories:
- **metadata**: Price, discount, date queries → BM25-heavy (exact terms matter)
- **visual**: Color, shape, appearance queries → visual kNN-heavy (when available)
- **factual**: Ingredient, comparison, how-to queries → BM25-heavy (specific terms)
- **general**: Broad browsing queries → semantic-heavy (meaning matters)

Phase B1: Rule-based regex classification (no model required).
Future: Graduate to Qwen2.5-0.5B classification for ambiguous queries.
"""
import re
from dataclasses import dataclass
from typing import Literal

from app.logging_config import get_logger

logger = get_logger(__name__)

IntentType = Literal["metadata", "visual", "factual", "general"]


@dataclass(frozen=True)
class SearchIntent:
    """Classified intent with recommended search parameters.

    Attributes:
        intent_type: One of metadata / visual / factual / general.
        alpha: Recommended BM25-vs-kNN blend (0.0 = pure BM25, 1.0 = pure kNN).
        visual_weight: Weight for visual kNN in 3-way RRF (0.0 = disabled).
        text_knn_weight: Weight for text kNN in 3-way RRF.
        bm25_weight: Weight for BM25 in 3-way RRF.
        matched_patterns: Which regex patterns triggered this intent (for debugging).
    """
    intent_type: IntentType
    alpha: float
    visual_weight: float
    text_knn_weight: float
    bm25_weight: float
    matched_patterns: tuple[str, ...] = ()


# -----------------------------------------------------------------------
# Pattern definitions
# -----------------------------------------------------------------------

# Metadata intent: prices, discounts, dates, brand-specific queries
_METADATA_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("price_number", re.compile(r"\d+[만천백]?\s*원")),
    ("discount", re.compile(r"할인|세일|특가|쿠폰|프로모션|무료배송")),
    ("date_pattern", re.compile(r"\d{4}[-/.]\d{1,2}|오늘|어제|이번\s*주|지난\s*주|이번\s*달")),
    ("price_range", re.compile(r"가격대|가격\s*비교|얼마|최저가|최고가")),
    ("quantity", re.compile(r"\d+\s*(개|세트|팩|박스|ml|g|kg)")),
]

# Visual intent: colors, shapes, appearance, product visuals
_VISUAL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("color", re.compile(r"빨간|빨강|파란|파랑|노란|노랑|초록|검은|검정|흰|하얀|분홍|핑크|베이지|브라운|골드|실버|네이비|보라|오렌지|카키")),
    ("pattern_texture", re.compile(r"무늬|패턴|줄무늬|체크|꽃무늬|도트|스트라이프|레이스|시스루")),
    ("size_shape", re.compile(r"크기|사이즈|큰|작은|미니|대용량|소용량|컴팩트")),
    ("appearance", re.compile(r"모양|디자인|생긴|보이는|착용|입고|신고|들고|쓰고")),
    ("visual_verb", re.compile(r"보여주|보여줘|어떻게\s*생|어떤\s*색")),
]

# Factual intent: ingredients, effects, comparisons, how-to
_FACTUAL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ingredient", re.compile(r"성분|함량|원료|추출물|히알루론|레티놀|비타민|나이아신|세라마이드|콜라겐")),
    ("effect", re.compile(r"효능|효과|기능|장점|단점|부작용")),
    ("howto", re.compile(r"사용법|사용방법|바르는|쓰는\s*법|순서|단계")),
    ("comparison", re.compile(r"비교|차이|vs|대|좋은|나은|추천")),
    ("specification", re.compile(r"SPF|PA\+|용량|유통기한|제조일", re.IGNORECASE)),
]

# Intent → search parameter mapping
_INTENT_PARAMS: dict[IntentType, tuple[float, float, float, float]] = {
    # (alpha, visual_weight, text_knn_weight, bm25_weight)
    "metadata": (0.0, 0.0, 0.0, 1.0),      # Pure BM25 for exact term matching
    "visual":   (0.7, 0.4, 0.35, 0.25),     # Visual kNN dominant when available
    "factual":  (0.3, 0.1, 0.3, 0.6),       # BM25-heavy for specific terms
    "general":  (0.7, 0.25, 0.45, 0.3),     # Semantic-heavy for broad queries
}


def classify_intent(query: str) -> SearchIntent:
    """Classify a Korean livecommerce search query into an intent category.

    Uses rule-based regex pattern matching. Falls back to "general" intent
    when no specific patterns match.

    Args:
        query: Raw user search query string.

    Returns:
        SearchIntent with classified type and recommended search parameters.
    """
    if not query or not query.strip():
        alpha, vis, text, bm25 = _INTENT_PARAMS["general"]
        return SearchIntent(
            intent_type="general",
            alpha=alpha,
            visual_weight=vis,
            text_knn_weight=text,
            bm25_weight=bm25,
        )

    query_lower = query.strip().lower()

    # Check each intent category and collect matched patterns
    metadata_matches = _match_patterns(query_lower, _METADATA_PATTERNS)
    visual_matches = _match_patterns(query_lower, _VISUAL_PATTERNS)
    factual_matches = _match_patterns(query_lower, _FACTUAL_PATTERNS)

    # Priority: metadata > factual > visual > general
    # Metadata is highest priority because exact term matching is critical
    # for price/discount queries regardless of other signals.
    if metadata_matches:
        intent_type: IntentType = "metadata"
        matched = metadata_matches
    elif factual_matches and len(factual_matches) >= len(visual_matches):
        intent_type = "factual"
        matched = factual_matches
    elif visual_matches:
        intent_type = "visual"
        matched = visual_matches
    else:
        intent_type = "general"
        matched = ()

    alpha, vis, text, bm25 = _INTENT_PARAMS[intent_type]

    intent = SearchIntent(
        intent_type=intent_type,
        alpha=alpha,
        visual_weight=vis,
        text_knn_weight=text,
        bm25_weight=bm25,
        matched_patterns=matched,
    )

    logger.debug(
        "query_intent_classified",
        query=query[:50],
        intent_type=intent_type,
        matched_patterns=matched,
        alpha=alpha,
    )

    return intent


def _match_patterns(
    query: str,
    patterns: list[tuple[str, re.Pattern[str]]],
) -> tuple[str, ...]:
    """Return names of patterns that match the query."""
    return tuple(name for name, pattern in patterns if pattern.search(query))
