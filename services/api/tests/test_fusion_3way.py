# pyright: reportUnknownMemberType=false, reportUnusedFunction=false, reportExplicitAny=false, reportAny=false

from collections.abc import Generator
from types import SimpleNamespace
from typing import Any, TypeAlias
from unittest.mock import patch

import pytest

from app.modules.search.fusion import QUALITY_FLOOR, RankedItem, compute_weighted_rrf
from app.modules.search.intent import classify_intent

Hit: TypeAlias = dict[str, Any]


def _make_hit(doc_id: str, video_id: str, score: float, transcript_chars: int = 100) -> Hit:
    return {
        "_id": doc_id,
        "_score": score,
        "_source": {
            "video_id": video_id,
            "transcript_char_count_normalized": transcript_chars,
        },
    }


def _doc(results: list[RankedItem], doc_id: str) -> RankedItem:
    return next(item for item in results if item.doc_id == doc_id)


def _rrf(rank: int, k: int = 60) -> float:
    return 1.0 / (k + rank)


@pytest.fixture(autouse=True)
def _patch_settings() -> Generator[None, None, None]:
    with patch("app.modules.search.fusion.get_settings", return_value=SimpleNamespace(search_rrf_k=60)):
        yield


class TestComputeWeightedRRF3Way:
    def test_all_three_signals_equal_weights(self) -> None:
        lexical = [_make_hit("doc_all", "v1", 10.0), _make_hit("doc_lex", "v2", 9.0)]
        vector = [_make_hit("doc_all", "v1", 0.9), _make_hit("doc_vec", "v3", 0.8)]
        visual = [_make_hit("doc_all", "v1", 0.95), _make_hit("doc_vis", "v4", 0.7)]

        results = compute_weighted_rrf(
            lexical,
            vector,
            visual,
            bm25_weight=0.33,
            text_knn_weight=0.33,
            visual_weight=0.33,
        )

        top = results[0]
        expected_each = 0.33 * _rrf(1)
        assert top.doc_id == "doc_all"
        assert top.lexical_contribution == pytest.approx(expected_each)
        assert top.vector_contribution == pytest.approx(expected_each)
        assert top.visual_contribution == pytest.approx(expected_each)
        assert top.fused_score == pytest.approx(expected_each * 3)

    def test_only_bm25_signal(self) -> None:
        lexical = [_make_hit("doc1", "v1", 10.0), _make_hit("doc2", "v2", 9.0)]

        results = compute_weighted_rrf(
            lexical,
            [],
            [],
            bm25_weight=1.0,
            text_knn_weight=0.0,
            visual_weight=0.0,
        )

        assert [item.doc_id for item in results] == ["doc1", "doc2"]
        assert results[0].lexical_contribution == pytest.approx(_rrf(1))
        assert results[0].vector_contribution == 0.0
        assert results[0].visual_contribution == 0.0

    def test_only_text_knn_signal(self) -> None:
        vector = [_make_hit("doc2", "v2", 0.9), _make_hit("doc1", "v1", 0.8)]

        results = compute_weighted_rrf(
            [],
            vector,
            [],
            bm25_weight=0.0,
            text_knn_weight=1.0,
            visual_weight=0.0,
        )

        assert [item.doc_id for item in results] == ["doc2", "doc1"]
        assert results[0].vector_contribution == pytest.approx(_rrf(1))
        assert results[0].lexical_contribution == 0.0
        assert results[0].visual_contribution == 0.0

    def test_only_visual_knn_signal(self) -> None:
        visual = [_make_hit("doc3", "v3", 0.99), _make_hit("doc4", "v4", 0.95)]

        results = compute_weighted_rrf(
            [],
            [],
            visual,
            bm25_weight=0.0,
            text_knn_weight=0.0,
            visual_weight=1.0,
        )

        assert [item.doc_id for item in results] == ["doc3", "doc4"]
        assert results[0].visual_contribution == pytest.approx(_rrf(1))
        assert results[0].lexical_contribution == 0.0
        assert results[0].vector_contribution == 0.0

    def test_two_way_bm25_and_text(self) -> None:
        lexical = [_make_hit("doc_a", "v1", 10.0), _make_hit("doc_b", "v2", 9.0)]
        vector = [_make_hit("doc_b", "v2", 0.9), _make_hit("doc_c", "v3", 0.8)]

        results = compute_weighted_rrf(
            lexical,
            vector,
            [],
            bm25_weight=0.6,
            text_knn_weight=0.4,
            visual_weight=0.0,
        )

        doc_b = _doc(results, "doc_b")
        assert doc_b.lexical_rank == 2
        assert doc_b.vector_rank == 1
        assert doc_b.visual_rank is None
        assert doc_b.visual_contribution == 0.0

    def test_two_way_text_and_visual(self) -> None:
        vector = [_make_hit("doc_t", "v1", 0.9), _make_hit("doc_tv", "v2", 0.85)]
        visual = [_make_hit("doc_tv", "v2", 0.92), _make_hit("doc_v", "v3", 0.8)]

        results = compute_weighted_rrf(
            [],
            vector,
            visual,
            bm25_weight=0.0,
            text_knn_weight=0.45,
            visual_weight=0.55,
        )

        doc_tv = _doc(results, "doc_tv")
        assert doc_tv.lexical_rank is None
        assert doc_tv.vector_rank == 2
        assert doc_tv.visual_rank == 1
        assert doc_tv.lexical_contribution == 0.0

    def test_document_in_all_three_lists_contributions(self) -> None:
        lexical = [_make_hit("doc_x", "v1", 10.0), _make_hit("other", "v2", 9.0)]
        vector = [_make_hit("a", "v3", 0.9), _make_hit("b", "v4", 0.8), _make_hit("doc_x", "v1", 0.7)]
        visual = [_make_hit("doc_x", "v1", 0.95)]

        results = compute_weighted_rrf(
            lexical,
            vector,
            visual,
            bm25_weight=0.25,
            text_knn_weight=0.35,
            visual_weight=0.4,
        )

        doc_x = _doc(results, "doc_x")
        assert doc_x.lexical_contribution == pytest.approx(0.25 * _rrf(1))
        assert doc_x.vector_contribution == pytest.approx(0.35 * _rrf(3))
        assert doc_x.visual_contribution == pytest.approx(0.4 * _rrf(1))
        assert doc_x.fused_score == pytest.approx(
            doc_x.lexical_contribution + doc_x.vector_contribution + doc_x.visual_contribution
        )

    def test_document_in_one_list_has_zero_other_contributions(self) -> None:
        lexical = [_make_hit("doc_lex_only", "v1", 10.0)]
        vector = [_make_hit("doc_vec_only", "v2", 0.9)]
        visual = [_make_hit("doc_vis_only", "v3", 0.95)]

        results = compute_weighted_rrf(
            lexical,
            vector,
            visual,
            bm25_weight=0.5,
            text_knn_weight=0.3,
            visual_weight=0.2,
        )

        item = _doc(results, "doc_lex_only")
        assert item.lexical_contribution > 0.0
        assert item.vector_contribution == 0.0
        assert item.visual_contribution == 0.0

    def test_document_in_two_of_three_lists_partial_fusion(self) -> None:
        lexical = [_make_hit("doc_lv", "v1", 10.0)]
        visual = [_make_hit("doc_lv", "v1", 0.97)]

        results = compute_weighted_rrf(
            lexical,
            [],
            visual,
            bm25_weight=0.7,
            text_knn_weight=0.0,
            visual_weight=0.3,
        )

        item = _doc(results, "doc_lv")
        assert item.lexical_contribution == pytest.approx(0.7 * _rrf(1))
        assert item.vector_contribution == 0.0
        assert item.visual_contribution == pytest.approx(0.3 * _rrf(1))
        assert item.fused_score == pytest.approx(item.lexical_contribution + item.visual_contribution)

    def test_empty_results_for_all_three_returns_empty(self) -> None:
        results = compute_weighted_rrf(
            [],
            [],
            [],
            bm25_weight=0.33,
            text_knn_weight=0.33,
            visual_weight=0.34,
        )
        assert results == []

    def test_higher_bm25_weight_increases_bm25_contribution(self) -> None:
        lexical = [_make_hit("doc1", "v1", 10.0)]

        low_weight = compute_weighted_rrf(
            lexical,
            [],
            [],
            bm25_weight=0.2,
            text_knn_weight=0.0,
            visual_weight=0.0,
        )
        high_weight = compute_weighted_rrf(
            lexical,
            [],
            [],
            bm25_weight=0.8,
            text_knn_weight=0.0,
            visual_weight=0.0,
        )

        assert high_weight[0].lexical_contribution > low_weight[0].lexical_contribution

    def test_higher_visual_weight_increases_visual_contribution(self) -> None:
        visual = [_make_hit("doc1", "v1", 0.99)]

        low_weight = compute_weighted_rrf(
            [],
            [],
            visual,
            bm25_weight=0.0,
            text_knn_weight=0.0,
            visual_weight=0.2,
        )
        high_weight = compute_weighted_rrf(
            [],
            [],
            visual,
            bm25_weight=0.0,
            text_knn_weight=0.0,
            visual_weight=0.8,
        )

        assert high_weight[0].visual_contribution > low_weight[0].visual_contribution

    def test_quality_factor_floor_applied_for_short_transcript(self) -> None:
        lexical = [_make_hit("short_doc", "v1", 10.0, transcript_chars=10)]

        results = compute_weighted_rrf(
            lexical,
            [],
            [],
            bm25_weight=1.0,
            text_knn_weight=0.0,
            visual_weight=0.0,
        )

        item = results[0]
        assert item.quality_factor == pytest.approx(QUALITY_FLOOR)
        assert item.quality_factor == pytest.approx(0.85)
        assert item.adjusted_score == pytest.approx(item.fused_score * QUALITY_FLOOR)

    def test_sorting_is_adjusted_score_descending(self) -> None:
        lexical = [
            _make_hit("doc_high", "v1", 10.0, transcript_chars=100),
            _make_hit("doc_mid", "v2", 9.0, transcript_chars=100),
            _make_hit("doc_low", "v3", 8.0, transcript_chars=10),
        ]

        results = compute_weighted_rrf(
            lexical,
            [],
            [],
            bm25_weight=1.0,
            text_knn_weight=0.0,
            visual_weight=0.0,
        )

        adjusted_scores = [item.adjusted_score for item in results]
        assert adjusted_scores == sorted(adjusted_scores, reverse=True)

    def test_ranked_item_visual_fields_present(self) -> None:
        visual = [_make_hit("doc1", "v1", 0.91)]

        results = compute_weighted_rrf(
            [],
            [],
            visual,
            bm25_weight=0.0,
            text_knn_weight=0.0,
            visual_weight=1.0,
        )

        item = results[0]
        assert isinstance(item, RankedItem)
        assert hasattr(item, "visual_rank")
        assert hasattr(item, "visual_score")
        assert hasattr(item, "visual_contribution")
        assert item.visual_rank == 1
        assert item.visual_score == pytest.approx(0.91)
        assert item.visual_contribution == pytest.approx(_rrf(1))

    def test_visual_intent_weights_025_035_04(self) -> None:
        intent = classify_intent("빨간 립스틱")
        assert intent.bm25_weight == pytest.approx(0.25)
        assert intent.text_knn_weight == pytest.approx(0.35)
        assert intent.visual_weight == pytest.approx(0.4)

        lexical = [_make_hit("doc_bm", "v1", 10.0)]
        vector = [_make_hit("doc_text", "v2", 0.95)]
        visual = [_make_hit("doc_vis", "v3", 0.99)]

        results = compute_weighted_rrf(
            lexical,
            vector,
            visual,
            bm25_weight=intent.bm25_weight,
            text_knn_weight=intent.text_knn_weight,
            visual_weight=intent.visual_weight,
        )

        doc_vis = _doc(results, "doc_vis")
        assert doc_vis.visual_contribution == pytest.approx(0.4 * _rrf(1))

    def test_metadata_intent_weights_pure_bm25(self) -> None:
        intent = classify_intent("할인 쿠폰")
        assert intent.bm25_weight == pytest.approx(1.0)
        assert intent.text_knn_weight == pytest.approx(0.0)
        assert intent.visual_weight == pytest.approx(0.0)

        lexical = [_make_hit("doc_bm", "v1", 10.0)]
        vector = [_make_hit("doc_text", "v2", 0.95)]
        visual = [_make_hit("doc_vis", "v3", 0.99)]

        results = compute_weighted_rrf(
            lexical,
            vector,
            visual,
            bm25_weight=intent.bm25_weight,
            text_knn_weight=intent.text_knn_weight,
            visual_weight=intent.visual_weight,
        )

        doc_bm = _doc(results, "doc_bm")
        assert doc_bm.lexical_contribution == pytest.approx(_rrf(1))
        assert doc_bm.vector_contribution == 0.0
        assert doc_bm.visual_contribution == 0.0

    def test_rrf_formula_rank1_with_k60(self) -> None:
        lexical = [_make_hit("doc1", "v1", 10.0)]

        results = compute_weighted_rrf(
            lexical,
            [],
            [],
            bm25_weight=0.5,
            text_knn_weight=0.0,
            visual_weight=0.0,
        )

        assert results[0].lexical_contribution == pytest.approx(0.5 * (1.0 / 61.0))

    def test_rrf_formula_rank3_with_k60(self) -> None:
        lexical = [
            _make_hit("a", "v1", 10.0),
            _make_hit("b", "v2", 9.0),
            _make_hit("doc3", "v3", 8.0),
        ]

        results = compute_weighted_rrf(
            lexical,
            [],
            [],
            bm25_weight=1.0,
            text_knn_weight=0.0,
            visual_weight=0.0,
        )

        doc3 = _doc(results, "doc3")
        assert doc3.lexical_rank == 3
        assert doc3.lexical_contribution == pytest.approx(1.0 / 63.0)

    def test_fused_score_equals_sum_of_three_contributions(self) -> None:
        lexical = [_make_hit("doc", "v1", 10.0)]
        vector = [_make_hit("doc", "v1", 0.9)]
        visual = [_make_hit("doc", "v1", 0.95)]

        results = compute_weighted_rrf(
            lexical,
            vector,
            visual,
            bm25_weight=0.2,
            text_knn_weight=0.3,
            visual_weight=0.5,
        )

        item = results[0]
        assert item.fused_score == pytest.approx(
            item.lexical_contribution + item.vector_contribution + item.visual_contribution
        )

    def test_quality_factor_can_change_final_ranking(self) -> None:
        lexical = [
            _make_hit("doc_short", "v1", 10.0, transcript_chars=10),
            _make_hit("doc_full", "v2", 9.0, transcript_chars=100),
        ]

        results = compute_weighted_rrf(
            lexical,
            [],
            [],
            bm25_weight=1.0,
            text_knn_weight=0.0,
            visual_weight=0.0,
        )

        assert results[0].doc_id == "doc_full"
        assert _doc(results, "doc_short").quality_factor == pytest.approx(QUALITY_FLOOR)

    def test_missing_signal_rank_is_none(self) -> None:
        lexical = [_make_hit("doc1", "v1", 10.0)]

        results = compute_weighted_rrf(
            lexical,
            [],
            [],
            bm25_weight=1.0,
            text_knn_weight=0.0,
            visual_weight=0.0,
        )

        item = results[0]
        assert item.vector_rank is None
        assert item.visual_rank is None

    def test_deterministic_order_for_same_input(self) -> None:
        lexical = [_make_hit(f"doc{i}", f"v{i}", 10.0 - i) for i in range(6)]
        vector = [_make_hit(f"doc{i}", f"v{i}", 1.0 - i * 0.1) for i in range(6)]
        visual = [_make_hit(f"doc{i}", f"v{i}", 0.9 - i * 0.1) for i in range(6)]

        results1 = compute_weighted_rrf(
            lexical,
            vector,
            visual,
            bm25_weight=0.3,
            text_knn_weight=0.35,
            visual_weight=0.35,
        )
        results2 = compute_weighted_rrf(
            lexical,
            vector,
            visual,
            bm25_weight=0.3,
            text_knn_weight=0.35,
            visual_weight=0.35,
        )

        assert [item.doc_id for item in results1] == [item.doc_id for item in results2]
