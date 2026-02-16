from dataclasses import asdict
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.search.eval import (
    EvalSummary,
    QueryResult,
    check_constraint,
    compute_hit_mrr_at_10,
    evaluate_query,
    run_search_evaluation,
)
from app.modules.search.fusion import RankedItem


def test_check_constraint_true_false_cases():
    assert check_constraint(
        "G01",
        {
            "video_title": "오설록 티하우스 소개",
            "transcript_norm": "무관",
        },
    )
    assert not check_constraint(
        "G01",
        {
            "video_title": "브랜드 소개",
            "transcript_norm": "오설록 언급",
        },
    )
    assert check_constraint(
        "G04",
        {
            "transcript_norm": "오늘은 로션을 발라요",
            "product_entities": [],
        },
    )
    assert not check_constraint(
        "G04",
        {
            "transcript_norm": "오늘은 크림을 발라요",
            "product_entities": ["세럼"],
        },
    )


def test_negative_query_constraint_always_false():
    assert not check_constraint("G15", {"transcript_norm": "자동차 엔진 오일"})
    assert not check_constraint("G15", {"video_title": "자동차 엔진 오일"})


def test_metric_calculation_rank3_hit():
    items = [
        RankedItem(doc_id="s1", video_id="v1", source={"transcript_norm": "다름"}),
        RankedItem(doc_id="s2", video_id="v2", source={"transcript_norm": "다름"}),
        RankedItem(doc_id="s3", video_id="v3", source={"transcript_norm": "세럼 소개"}),
    ]

    hit_at_10, mrr_at_10, first_hit_rank, _ = compute_hit_mrr_at_10(items, "G03")

    assert hit_at_10 == 1
    assert abs(mrr_at_10 - (1 / 3)) < 1e-9
    assert first_hit_rank == 3


def test_metric_calculation_no_hit():
    items = [
        RankedItem(doc_id="s1", video_id="v1", source={"transcript_norm": "다름"}),
        RankedItem(doc_id="s2", video_id="v2", source={"transcript_norm": "여전히 다름"}),
    ]

    hit_at_10, mrr_at_10, first_hit_rank, _ = compute_hit_mrr_at_10(items, "G03")

    assert hit_at_10 == 0
    assert mrr_at_10 == 0.0
    assert first_hit_rank is None


def test_output_schema_fields():
    query_result = QueryResult(
        query_id="G03",
        query="세럼",
        category="product",
        hit_at_10=1,
        mrr_at_10=1.0,
        first_hit_rank=1,
        total_candidates=10,
        top_10_results=[],
        signal_attribution="balanced",
    )
    summary = EvalSummary(
        timestamp="2026-01-01T00:00:00+00:00",
        org_id="org-1",
        config={"alpha": 0.5},
        overall_hit_at_10=0.7,
        overall_mrr_at_10=0.4,
        per_category={"product": {"hit_at_10": 1.0, "mrr_at_10": 1.0, "count": 1}},
        query_results=[query_result],
        negative_query_correct=True,
    )

    query_result_fields = set(asdict(query_result).keys())
    summary_fields = set(asdict(summary).keys())

    assert query_result_fields == {
        "query_id",
        "query",
        "category",
        "hit_at_10",
        "mrr_at_10",
        "first_hit_rank",
        "total_candidates",
        "top_10_results",
        "signal_attribution",
    }
    assert summary_fields == {
        "timestamp",
        "org_id",
        "config",
        "overall_hit_at_10",
        "overall_mrr_at_10",
        "per_category",
        "query_results",
        "negative_query_correct",
    }


@pytest.mark.asyncio
async def test_org_id_filter_always_present(mock_scene_opensearch_client: MagicMock):
    lexical_mock: AsyncMock = AsyncMock(
        return_value=[
            {
                "_id": "scene-1",
                "_score": 10.0,
                "_source": {
                    "scene_id": "scene-1",
                    "video_id": "video-1",
                    "transcript_norm": "세럼 설명",
                },
            }
        ]
    )
    vector_mock: AsyncMock = AsyncMock(return_value=[])
    mock_scene_opensearch_client.search_lexical = lexical_mock
    mock_scene_opensearch_client.search_vector = vector_mock

    with patch("app.modules.search.eval.get_query_embedding", new=AsyncMock(return_value=[0.1, 0.2])):
        _ = await evaluate_query(
            mock_scene_opensearch_client,
            query_id="G03",
            query="세럼",
            category="product",
            org_id="org-abc",
            alpha=0.5,
        )

    assert lexical_mock.await_args is not None
    assert vector_mock.await_args is not None
    lexical_kwargs = cast(dict[str, object], lexical_mock.await_args.kwargs)
    vector_kwargs = cast(dict[str, object], vector_mock.await_args.kwargs)
    assert lexical_kwargs["org_id"] == "org-abc"
    assert vector_kwargs["org_id"] == "org-abc"
    assert lexical_kwargs["filters"] == {}
    assert vector_kwargs["filters"] == {}


@pytest.mark.asyncio
async def test_run_search_evaluation_mocked_pipeline(mock_scene_opensearch_client: MagicMock):
    mock_scene_opensearch_client.search_lexical = AsyncMock(return_value=[])
    mock_scene_opensearch_client.search_vector = AsyncMock(return_value=[])

    with patch("app.modules.search.eval.get_query_embedding", new=AsyncMock(return_value=[0.1, 0.2])):
        result = await run_search_evaluation(org_id="org-xyz", scene_client=mock_scene_opensearch_client)

    assert isinstance(result, EvalSummary)
    assert result.org_id == "org-xyz"
    assert len(result.query_results) == 15
    assert result.negative_query_correct
