import pytest
from unittest.mock import patch, AsyncMock

from app.modules.search.fusion import RankedItem
from app.modules.search.reranker import (
    RerankerService,
    build_reranker_document,
    apply_reranking,
    _mock_scores,
)


def _make_ranked_item(doc_id: str, video_id: str, adjusted_score: float, **source_fields) -> RankedItem:
    source = {"video_id": video_id, "scene_id": doc_id, **source_fields}
    return RankedItem(
        doc_id=doc_id,
        video_id=video_id,
        source=source,
        adjusted_score=adjusted_score,
        fused_score=adjusted_score,
    )


class TestBuildRerankerDocument:
    def test_combines_all_fields(self):
        source = {
            "scene_caption": "A green product",
            "transcript_norm": "this is great",
            "ocr_text_raw": "SALE 50%",
        }
        result = build_reranker_document(source)
        assert result == "A green product this is great SALE 50%"

    def test_handles_missing_fields(self):
        source = {"scene_caption": "only caption"}
        result = build_reranker_document(source)
        assert result == "only caption"

    def test_handles_none_fields(self):
        source = {"scene_caption": None, "transcript_norm": "text", "ocr_text_raw": None}
        result = build_reranker_document(source)
        assert result == "text"

    def test_empty_source(self):
        result = build_reranker_document({})
        assert result == ""

    def test_empty_string_fields_skipped(self):
        source = {"scene_caption": "", "transcript_norm": "", "ocr_text_raw": "OCR"}
        result = build_reranker_document(source)
        assert result == "OCR"


class TestMockScores:
    def test_returns_correct_count(self):
        scores = _mock_scores("query", ["doc1", "doc2", "doc3"])
        assert len(scores) == 3

    def test_scores_in_valid_range(self):
        scores = _mock_scores("test query", [f"doc {i}" for i in range(50)])
        for score in scores:
            assert 0.0 <= score <= 1.0

    def test_deterministic(self):
        scores_a = _mock_scores("query", ["doc1", "doc2"])
        scores_b = _mock_scores("query", ["doc1", "doc2"])
        assert scores_a == scores_b

    def test_different_queries_different_scores(self):
        scores_a = _mock_scores("query A", ["doc1"])
        scores_b = _mock_scores("query B", ["doc1"])
        assert scores_a != scores_b

    def test_empty_documents(self):
        scores = _mock_scores("query", [])
        assert scores == []


class TestRerankerServiceMock:
    def test_score_pairs_mock_mode(self):
        with patch("app.modules.search.reranker.get_settings") as mock_settings:
            mock_settings.return_value.reranker_use_mock = True
            mock_settings.return_value.reranker_model = "BAAI/bge-reranker-v2-m3"
            service = RerankerService()
            scores = service.score_pairs("test query", ["doc1", "doc2", "doc3"])
            assert len(scores) == 3
            for s in scores:
                assert 0.0 <= s <= 1.0

    def test_score_pairs_empty_documents(self):
        with patch("app.modules.search.reranker.get_settings") as mock_settings:
            mock_settings.return_value.reranker_use_mock = True
            mock_settings.return_value.reranker_model = "BAAI/bge-reranker-v2-m3"
            service = RerankerService()
            scores = service.score_pairs("query", [])
            assert scores == []


class TestApplyReranking:
    @pytest.mark.asyncio
    async def test_reorders_items(self):
        items = [
            _make_ranked_item("d1", "v1", 1.0, scene_caption="irrelevant content"),
            _make_ranked_item("d2", "v2", 0.9, scene_caption="very relevant match"),
            _make_ranked_item("d3", "v3", 0.8, scene_caption="somewhat relevant"),
        ]
        remaining = [
            _make_ranked_item("d4", "v4", 0.1, scene_caption="tail item"),
        ]

        with patch("app.modules.search.reranker.get_settings") as mock_settings:
            mock_settings.return_value.reranker_enabled = True
            mock_settings.return_value.reranker_use_mock = True
            mock_settings.return_value.reranker_model = "BAAI/bge-reranker-v2-m3"
            mock_settings.return_value.reranker_top_k = 50
            mock_settings.return_value.reranker_blend_weight = 0.7

            result = await apply_reranking("test query", items, remaining)

        # All items present (3 reranked + 1 remaining)
        assert len(result) == 4
        # Remaining item is always last
        assert result[-1].doc_id == "d4"
        # All reranked items have reranker_score set
        for item in result[:3]:
            assert item.reranker_score is not None

    @pytest.mark.asyncio
    async def test_remaining_items_unchanged(self):
        items = [_make_ranked_item("d1", "v1", 1.0, scene_caption="top")]
        remaining = [
            _make_ranked_item("d2", "v2", 0.5, scene_caption="tail1"),
            _make_ranked_item("d3", "v3", 0.3, scene_caption="tail2"),
        ]

        with patch("app.modules.search.reranker.get_settings") as mock_settings:
            mock_settings.return_value.reranker_enabled = True
            mock_settings.return_value.reranker_use_mock = True
            mock_settings.return_value.reranker_model = "BAAI/bge-reranker-v2-m3"
            mock_settings.return_value.reranker_top_k = 50
            mock_settings.return_value.reranker_blend_weight = 0.7

            result = await apply_reranking("query", items, remaining)

        # Remaining items have no reranker_score
        assert result[1].reranker_score is None
        assert result[2].reranker_score is None
        assert result[1].doc_id == "d2"
        assert result[2].doc_id == "d3"

    @pytest.mark.asyncio
    async def test_empty_ranked_items(self):
        remaining = [_make_ranked_item("d1", "v1", 0.5)]

        with patch("app.modules.search.reranker.get_settings") as mock_settings:
            mock_settings.return_value.reranker_enabled = True
            mock_settings.return_value.reranker_use_mock = True
            mock_settings.return_value.reranker_model = "BAAI/bge-reranker-v2-m3"
            mock_settings.return_value.reranker_top_k = 50
            mock_settings.return_value.reranker_blend_weight = 0.7

            result = await apply_reranking("query", [], remaining)

        assert len(result) == 1
        assert result[0].doc_id == "d1"

    @pytest.mark.asyncio
    async def test_preserves_original_metadata(self):
        item = _make_ranked_item("d1", "v1", 0.95, scene_caption="test")
        item.lexical_rank = 1
        item.lexical_score = 10.5
        item.vector_rank = 3
        item.fused_score = 0.95

        with patch("app.modules.search.reranker.get_settings") as mock_settings:
            mock_settings.return_value.reranker_enabled = True
            mock_settings.return_value.reranker_use_mock = True
            mock_settings.return_value.reranker_model = "BAAI/bge-reranker-v2-m3"
            mock_settings.return_value.reranker_top_k = 50
            mock_settings.return_value.reranker_blend_weight = 0.7

            result = await apply_reranking("query", [item], [])

        assert result[0].lexical_rank == 1
        assert result[0].lexical_score == 10.5
        assert result[0].vector_rank == 3
        assert result[0].fused_score == 0.95

    @pytest.mark.asyncio
    async def test_blend_weight_affects_scores(self):
        items = [
            _make_ranked_item("d1", "v1", 1.0, scene_caption="high rrf"),
            _make_ranked_item("d2", "v2", 0.5, scene_caption="low rrf"),
        ]

        with patch("app.modules.search.reranker.get_settings") as mock_settings:
            mock_settings.return_value.reranker_enabled = True
            mock_settings.return_value.reranker_use_mock = True
            mock_settings.return_value.reranker_model = "BAAI/bge-reranker-v2-m3"
            mock_settings.return_value.reranker_top_k = 50
            mock_settings.return_value.reranker_blend_weight = 0.7

            result = await apply_reranking("query", items, [])

        # Both items should have adjusted_score set (blended)
        for item in result:
            assert item.adjusted_score > 0
            assert item.reranker_score is not None
