from __future__ import annotations

import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import cast

from app.config import get_settings
from app.modules.search.embedding import get_query_embedding
from app.modules.search.fusion import RankedItem, compute_weighted_rrf, diversify_results
from app.modules.search.scene_client import SceneSearchClient

GOLDEN_QUERIES = [
    {"id": "G01", "query": "오설록", "category": "brand"},
    {"id": "G02", "query": "장원영", "category": "brand"},
    {"id": "G03", "query": "세럼", "category": "product"},
    {"id": "G04", "query": "로션", "category": "product"},
    {"id": "G05", "query": "마스크", "category": "product"},
    {"id": "G06", "query": "메이크업", "category": "product"},
    {"id": "G07", "query": "바르는 방법", "category": "situational"},
    {"id": "G08", "query": "클렌징", "category": "situational"},
    {"id": "G09", "query": "할인", "category": "situational"},
    {"id": "G10", "query": "머신러닝 모델", "category": "seed_korean"},
    {"id": "G11", "query": "데이터베이스 최적화", "category": "seed_korean"},
    {"id": "G12", "query": "API 문서", "category": "mixed_lang"},
    {"id": "G13", "query": "scalability concerns", "category": "english"},
    {"id": "G14", "query": "quarterly results", "category": "english"},
    {"id": "G15", "query": "자동차 엔진 오일", "category": "negative"},
]


def check_constraint(query_id: str, source: dict[str, object]) -> bool:
    transcript = unicodedata.normalize("NFC", (cast(str | None, source.get("transcript_norm", "")) or "").lower())
    title = unicodedata.normalize("NFC", (cast(str | None, source.get("video_title", "")) or "").lower())
    kw_tags = cast(list[str] | None, source.get("keyword_tags", [])) or []
    prod_tags = cast(list[str] | None, source.get("product_tags", [])) or []
    prod_entities = cast(list[str] | None, source.get("product_entities", [])) or []

    constraints = {
        "G01": lambda: "오설록" in title,
        "G02": lambda: "장원영" in title or "원영" in title,
        "G03": lambda: "세럼" in transcript,
        "G04": lambda: "로션" in transcript or "로션" in [e.lower() for e in prod_entities],
        "G05": lambda: "마스크" in transcript or "마스크" in [e.lower() for e in prod_entities],
        "G06": lambda: "메이크업" in transcript or "메이크업" in [e.lower() for e in prod_entities],
        "G07": lambda: "바르" in transcript and "방법" in transcript,
        "G08": lambda: "클렌징" in transcript,
        "G09": lambda: "할인" in transcript or "price" in [t.lower() for t in kw_tags],
        "G10": lambda: "머신러닝" in transcript,
        "G11": lambda: "데이터베이스" in transcript and "최적화" in transcript,
        "G12": lambda: "api" in transcript and "문서" in transcript,
        "G13": lambda: "scalability" in transcript,
        "G14": lambda: "quarterly" in transcript and "results" in transcript,
        "G15": lambda: False,
    }
    _ = prod_tags
    checker = constraints.get(query_id)
    return checker() if checker else False


@dataclass
class QueryResult:
    query_id: str
    query: str
    category: str
    hit_at_10: int
    mrr_at_10: float
    first_hit_rank: int | None
    total_candidates: int
    top_10_results: list[dict[str, object]]
    signal_attribution: str


@dataclass
class EvalSummary:
    timestamp: str
    org_id: str
    config: dict[str, object]
    overall_hit_at_10: float
    overall_mrr_at_10: float
    per_category: dict[str, dict[str, float | int]]
    query_results: list[QueryResult]
    negative_query_correct: bool


TITLE_ONLY_QUERIES = {"G01", "G02"}


def _classify_signal(item: RankedItem | None, query_id: str) -> str:
    if item is None:
        if query_id in TITLE_ONLY_QUERIES:
            return "title_only"
        return "no_hit"

    lexical = item.lexical_contribution
    vector = item.vector_contribution
    if lexical == 0.0 and vector == 0.0:
        return "balanced"

    dominant = max(abs(lexical), abs(vector))
    if dominant == 0:
        return "balanced"

    relative_gap = abs(lexical - vector) / dominant
    if relative_gap <= 0.2:
        return "balanced"
    if lexical > vector:
        return "lexical_dominant"
    return "vector_dominant"


def _build_top_10_rows(items: list[RankedItem], query_id: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in items[:10]:
        source = item.source
        rows.append(
            {
                "scene_id": source.get("scene_id", item.doc_id),
                "video_id": source.get("video_id", ""),
                "fused_score": item.fused_score,
                "constraint_met": check_constraint(query_id, source),
                "signal_type": _classify_signal(item, query_id),
            }
        )
    return rows


def _compute_query_metrics(items: list[RankedItem], query_id: str) -> tuple[int, float, int | None, RankedItem | None]:
    for rank, item in enumerate(items[:10], start=1):
        if check_constraint(query_id, item.source):
            return 1, 1.0 / rank, rank, item
    return 0, 0.0, None, None


def compute_hit_mrr_at_10(items: list[RankedItem], query_id: str) -> tuple[int, float, int | None, RankedItem | None]:
    return _compute_query_metrics(items, query_id)


async def evaluate_query(
    scene_client: SceneSearchClient,
    *,
    query_id: str,
    query: str,
    category: str,
    org_id: str,
    alpha: float = 0.5,
) -> QueryResult:
    settings = get_settings()

    embedding = await get_query_embedding(query)
    lexical_results = await scene_client.search_lexical(
        query=query,
        org_id=org_id,
        filters={},
        size=200,
        include_ocr=True,
    )
    vector_results = await scene_client.search_vector(
        embedding=embedding,
        org_id=org_id,
        filters={},
        size=200,
    )

    ranked = compute_weighted_rrf(lexical_results, vector_results, alpha=alpha)
    diversified = diversify_results(
        ranked,
        max_per_video=settings.search_max_scenes_per_video,
        target_count=settings.search_page_size,
    )

    hit_at_10, mrr_at_10, first_hit_rank, first_hit_item = _compute_query_metrics(diversified, query_id)
    signal_attribution = _classify_signal(first_hit_item, query_id)

    return QueryResult(
        query_id=query_id,
        query=query,
        category=category,
        hit_at_10=hit_at_10,
        mrr_at_10=mrr_at_10,
        first_hit_rank=first_hit_rank,
        total_candidates=len(ranked),
        top_10_results=_build_top_10_rows(diversified, query_id),
        signal_attribution=signal_attribution,
    )


def _compute_aggregate_metrics(query_results: list[QueryResult]) -> tuple[float, float, dict[str, dict[str, float | int]]]:
    non_negative = [r for r in query_results if r.query_id != "G15"]
    if not non_negative:
        overall_hit_at_10 = 0.0
        overall_mrr_at_10 = 0.0
    else:
        overall_hit_at_10 = sum(r.hit_at_10 for r in non_negative) / len(non_negative)
        overall_mrr_at_10 = sum(r.mrr_at_10 for r in non_negative) / len(non_negative)

    per_category: dict[str, list[QueryResult]] = {}
    for result in query_results:
        per_category.setdefault(result.category, []).append(result)

    category_metrics: dict[str, dict[str, float | int]] = {}
    for category, items in per_category.items():
        category_metrics[category] = {
            "hit_at_10": sum(i.hit_at_10 for i in items) / len(items),
            "mrr_at_10": sum(i.mrr_at_10 for i in items) / len(items),
            "count": len(items),
        }

    return overall_hit_at_10, overall_mrr_at_10, category_metrics


async def run_search_evaluation(
    org_id: str,
    *,
    scene_client: SceneSearchClient | None = None,
    alpha: float = 0.5,
) -> EvalSummary:
    settings = get_settings()
    client = scene_client or SceneSearchClient()
    owns_client = scene_client is None

    try:
        query_results: list[QueryResult] = []
        for query_def in GOLDEN_QUERIES:
            query_results.append(
                await evaluate_query(
                    client,
                    query_id=query_def["id"],
                    query=query_def["query"],
                    category=query_def["category"],
                    org_id=org_id,
                    alpha=alpha,
                )
            )

        overall_hit_at_10, overall_mrr_at_10, per_category = _compute_aggregate_metrics(query_results)
        g15_result = next((r for r in query_results if r.query_id == "G15"), None)
        negative_query_correct = bool(g15_result and g15_result.hit_at_10 == 0)

        return EvalSummary(
            timestamp=datetime.now(tz=timezone.utc).isoformat(),
            org_id=org_id,
            config={
                "search_rrf_k": settings.search_rrf_k,
                "alpha": alpha,
                "search_page_size": settings.search_page_size,
                "search_max_scenes_per_video": settings.search_max_scenes_per_video,
                "search_lexical_top_k": 200,
                "search_vector_top_k": 200,
                "include_ocr": True,
            },
            overall_hit_at_10=overall_hit_at_10,
            overall_mrr_at_10=overall_mrr_at_10,
            per_category=per_category,
            query_results=query_results,
            negative_query_correct=negative_query_correct,
        )
    finally:
        if owns_client:
            await client.close()


def eval_summary_to_dict(summary: EvalSummary) -> dict[str, object]:
    data = asdict(summary)
    data["query_results"] = [asdict(item) for item in summary.query_results]
    return data
