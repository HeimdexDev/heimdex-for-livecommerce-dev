# pyright: reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnusedCallResult=false

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.search.intent import IntentType, SearchIntent
from app.modules.search.schemas import SearchFilters


def _intent(
    intent_type: IntentType,
    *,
    alpha: float,
    visual_weight: float,
    text_knn_weight: float,
    bm25_weight: float,
    matched_patterns: tuple[str, ...] = (),
) -> SearchIntent:
    return SearchIntent(
        intent_type=intent_type,
        alpha=alpha,
        visual_weight=visual_weight,
        text_knn_weight=text_knn_weight,
        bm25_weight=bm25_weight,
        matched_patterns=matched_patterns,
    )


@pytest.fixture
def org_id():
    return uuid4()


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.fixture
def mock_scene_opensearch():
    client = MagicMock()
    client.search_metadata = AsyncMock(return_value=[])
    client.search_lexical = AsyncMock(return_value=[])
    client.search_vector = AsyncMock(return_value=[])
    client.search_visual_vector = AsyncMock(return_value=[])
    client.get_facets = AsyncMock(
        return_value={
            "libraries": [],
            "source_types": [],
            "people": [],
        }
    )
    return client


@pytest.fixture
def mock_search_service(mock_session, mock_scene_opensearch):
    from app.modules.search.scene_service import SceneSearchService

    def _passthrough(ranked_items, *args, **kwargs):
        _ = (args, kwargs)
        return ranked_items

    with (
        patch("app.modules.search.scene_service.PeopleClusterLabelRepository") as mock_people_repo,
        patch("app.modules.search.scene_service.PeopleExcludePreferenceRepository"),
        patch("app.modules.search.scene_service.LibraryRepository") as mock_lib_repo,
        patch("app.modules.search.scene_service.get_query_embedding", new_callable=AsyncMock) as mock_embed,
        patch(
            "app.modules.search.scene_service.get_visual_query_embedding",
            new_callable=AsyncMock,
        ) as mock_visual_embed,
        patch("app.modules.search.scene_service.classify_intent") as mock_classify_intent,
        patch("app.modules.search.scene_service.compute_weighted_rrf") as mock_rrf,
        patch("app.modules.search.scene_service.diversify_results") as mock_diversify,
    ):
        mock_people_instance = MagicMock()
        mock_people_instance.list_by_org = AsyncMock(return_value=[])
        mock_people_repo.return_value = mock_people_instance

        mock_lib_instance = MagicMock()
        mock_lib_instance.list_by_org = AsyncMock(return_value=[])
        mock_lib_repo.return_value = mock_lib_instance

        mock_embed.return_value = [0.1] * 1024
        mock_visual_embed.return_value = [0.2] * 768
        mock_classify_intent.return_value = _intent(
            "general",
            alpha=0.7,
            visual_weight=0.25,
            text_knn_weight=0.45,
            bm25_weight=0.3,
        )
        mock_rrf.return_value = []
        mock_diversify.side_effect = _passthrough

        svc = SceneSearchService(mock_session, mock_scene_opensearch)
        yield svc, mock_scene_opensearch, {
            "get_query_embedding": mock_embed,
            "get_visual_query_embedding": mock_visual_embed,
            "classify_intent": mock_classify_intent,
            "compute_weighted_rrf": mock_rrf,
            "diversify_results": mock_diversify,
        }


async def _run_semantic_search(svc, org_id, query: str):
    return await svc.search(
        query=query,
        org_id=org_id,
        alpha=0.5,
        filters=SearchFilters(),
        search_mode="semantic",
    )


class TestVisualFusionSemanticMode:
    @pytest.mark.asyncio
    async def test_visual_enabled_visual_intent_calls_visual_search_with_0_4_weight(
        self, mock_search_service, org_id
    ):
        svc, os_client, mocks = mock_search_service
        svc.settings.visual_embedding_enabled = True
        mocks["classify_intent"].return_value = _intent(
            "visual",
            alpha=0.7,
            visual_weight=0.4,
            text_knn_weight=0.35,
            bm25_weight=0.25,
        )

        await _run_semantic_search(svc, org_id, "빨간색 원피스")

        os_client.search_visual_vector.assert_called_once()
        kwargs = mocks["compute_weighted_rrf"].call_args.kwargs
        assert kwargs["visual_weight"] == pytest.approx(0.4)

    @pytest.mark.asyncio
    async def test_visual_enabled_metadata_intent_skips_visual_search(self, mock_search_service, org_id):
        svc, os_client, mocks = mock_search_service
        svc.settings.visual_embedding_enabled = True
        mocks["classify_intent"].return_value = _intent(
            "metadata",
            alpha=0.0,
            visual_weight=0.0,
            text_knn_weight=0.0,
            bm25_weight=1.0,
        )

        await _run_semantic_search(svc, org_id, "3만원 할인")

        os_client.search_visual_vector.assert_not_called()
        kwargs = mocks["compute_weighted_rrf"].call_args.kwargs
        assert kwargs["visual_weight"] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_visual_enabled_general_intent_calls_visual_search_with_0_25_weight(
        self, mock_search_service, org_id
    ):
        svc, os_client, mocks = mock_search_service
        svc.settings.visual_embedding_enabled = True
        mocks["classify_intent"].return_value = _intent(
            "general",
            alpha=0.7,
            visual_weight=0.25,
            text_knn_weight=0.45,
            bm25_weight=0.3,
        )

        await _run_semantic_search(svc, org_id, "봄 코디 추천")

        os_client.search_visual_vector.assert_called_once()
        kwargs = mocks["compute_weighted_rrf"].call_args.kwargs
        assert kwargs["visual_weight"] == pytest.approx(0.25)

    @pytest.mark.asyncio
    async def test_visual_enabled_factual_intent_calls_visual_search_with_0_1_weight(
        self, mock_search_service, org_id
    ):
        svc, os_client, mocks = mock_search_service
        svc.settings.visual_embedding_enabled = True
        mocks["classify_intent"].return_value = _intent(
            "factual",
            alpha=0.3,
            visual_weight=0.1,
            text_knn_weight=0.3,
            bm25_weight=0.6,
        )

        await _run_semantic_search(svc, org_id, "성분 비교 알려줘")

        os_client.search_visual_vector.assert_called_once()
        kwargs = mocks["compute_weighted_rrf"].call_args.kwargs
        assert kwargs["visual_weight"] == pytest.approx(0.1)

    @pytest.mark.asyncio
    async def test_visual_disabled_visual_intent_skips_visual_search_and_redistributes_weights(
        self, mock_search_service, org_id
    ):
        svc, os_client, mocks = mock_search_service
        svc.settings.visual_embedding_enabled = False
        mocks["classify_intent"].return_value = _intent(
            "visual",
            alpha=0.7,
            visual_weight=0.4,
            text_knn_weight=0.35,
            bm25_weight=0.25,
        )

        await _run_semantic_search(svc, org_id, "빨간색 원피스")

        os_client.search_visual_vector.assert_not_called()
        kwargs = mocks["compute_weighted_rrf"].call_args.kwargs
        assert kwargs["visual_weight"] == pytest.approx(0.0)
        assert kwargs["bm25_weight"] == pytest.approx(0.25 / 0.6, rel=1e-3)
        assert kwargs["text_knn_weight"] == pytest.approx(0.35 / 0.6, rel=1e-3)

    @pytest.mark.asyncio
    async def test_visual_disabled_does_not_call_get_visual_query_embedding(
        self, mock_search_service, org_id
    ):
        svc, _, mocks = mock_search_service
        svc.settings.visual_embedding_enabled = False
        mocks["classify_intent"].return_value = _intent(
            "visual",
            alpha=0.7,
            visual_weight=0.4,
            text_knn_weight=0.35,
            bm25_weight=0.25,
        )

        await _run_semantic_search(svc, org_id, "빨간색 원피스")

        mocks["get_visual_query_embedding"].assert_not_called()

    @pytest.mark.asyncio
    async def test_weight_redistribution_visual_disabled_visual_intent_exact_values(
        self, mock_search_service, org_id
    ):
        svc, _, mocks = mock_search_service
        svc.settings.visual_embedding_enabled = False
        mocks["classify_intent"].return_value = _intent(
            "visual",
            alpha=0.7,
            visual_weight=0.4,
            text_knn_weight=0.35,
            bm25_weight=0.25,
        )

        await _run_semantic_search(svc, org_id, "빨간색 원피스")

        kwargs = mocks["compute_weighted_rrf"].call_args.kwargs
        assert kwargs["bm25_weight"] == pytest.approx(0.417, abs=1e-3)
        assert kwargs["text_knn_weight"] == pytest.approx(0.583, abs=1e-3)
        assert kwargs["visual_weight"] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_embeddings_run_concurrently_via_asyncio_gather(self, mock_search_service, org_id):
        svc, _, mocks = mock_search_service
        svc.settings.visual_embedding_enabled = True
        mocks["classify_intent"].return_value = _intent(
            "visual",
            alpha=0.7,
            visual_weight=0.4,
            text_knn_weight=0.35,
            bm25_weight=0.25,
        )

        text_started = asyncio.Event()
        visual_started = asyncio.Event()
        release = asyncio.Event()

        async def slow_text_embedding(_query):
            text_started.set()
            await release.wait()
            return [0.1] * 1024

        async def slow_visual_embedding(_query):
            visual_started.set()
            await release.wait()
            return [0.2] * 768

        mocks["get_query_embedding"].side_effect = slow_text_embedding
        mocks["get_visual_query_embedding"].side_effect = slow_visual_embedding

        task = asyncio.create_task(_run_semantic_search(svc, org_id, "빨간색 원피스"))
        await asyncio.wait_for(text_started.wait(), timeout=0.5)
        await asyncio.wait_for(visual_started.wait(), timeout=0.5)
        release.set()
        await task

        assert text_started.is_set()
        assert visual_started.is_set()

    @pytest.mark.asyncio
    async def test_bm25_skipped_when_bm25_weight_zero(self, mock_search_service, org_id):
        svc, os_client, mocks = mock_search_service
        svc.settings.visual_embedding_enabled = True
        mocks["classify_intent"].return_value = _intent(
            "metadata",
            alpha=1.0,
            visual_weight=0.0,
            text_knn_weight=1.0,
            bm25_weight=0.0,
        )

        await _run_semantic_search(svc, org_id, "3만원 할인")

        os_client.search_lexical.assert_not_called()
        kwargs = mocks["compute_weighted_rrf"].call_args.kwargs
        assert kwargs["lexical_results"] == []
        assert kwargs["bm25_weight"] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_search_visual_vector_receives_visual_embedding_output(
        self, mock_search_service, org_id
    ):
        svc, os_client, mocks = mock_search_service
        svc.settings.visual_embedding_enabled = True
        expected_visual = [0.2] * 768
        mocks["get_visual_query_embedding"].return_value = expected_visual
        mocks["classify_intent"].return_value = _intent(
            "visual",
            alpha=0.7,
            visual_weight=0.4,
            text_knn_weight=0.35,
            bm25_weight=0.25,
        )

        await _run_semantic_search(svc, org_id, "빨간색 원피스")

        kwargs = os_client.search_visual_vector.call_args.kwargs
        assert kwargs["visual_embedding"] == expected_visual

    @pytest.mark.asyncio
    async def test_compute_weighted_rrf_receives_visual_results_and_weights(
        self, mock_search_service, org_id
    ):
        svc, os_client, mocks = mock_search_service
        svc.settings.visual_embedding_enabled = True
        os_client.search_vector.return_value = [{"scene_id": "text-1"}]
        os_client.search_visual_vector.return_value = [{"scene_id": "visual-1"}]
        os_client.search_lexical.return_value = [{"scene_id": "bm25-1"}]
        mocks["classify_intent"].return_value = _intent(
            "general",
            alpha=0.7,
            visual_weight=0.25,
            text_knn_weight=0.45,
            bm25_weight=0.3,
        )

        await _run_semantic_search(svc, org_id, "봄 코디 추천")

        kwargs = mocks["compute_weighted_rrf"].call_args.kwargs
        assert kwargs["vector_results"] == [{"scene_id": "text-1"}]
        assert kwargs["visual_results"] == [{"scene_id": "visual-1"}]
        assert kwargs["lexical_results"] == [{"scene_id": "bm25-1"}]
        assert kwargs["bm25_weight"] == pytest.approx(0.3)
        assert kwargs["text_knn_weight"] == pytest.approx(0.45)
        assert kwargs["visual_weight"] == pytest.approx(0.25)

    @pytest.mark.asyncio
    async def test_visual_enabled_zero_visual_weight_skips_visual_embedding(
        self, mock_search_service, org_id
    ):
        svc, os_client, mocks = mock_search_service
        svc.settings.visual_embedding_enabled = True
        mocks["classify_intent"].return_value = _intent(
            "metadata",
            alpha=0.0,
            visual_weight=0.0,
            text_knn_weight=0.0,
            bm25_weight=1.0,
        )

        await _run_semantic_search(svc, org_id, "3만원 할인")

        mocks["get_visual_query_embedding"].assert_not_called()
        os_client.search_visual_vector.assert_not_called()

    @pytest.mark.asyncio
    async def test_visual_disabled_general_intent_redistributes_to_0_4_0_6(
        self, mock_search_service, org_id
    ):
        svc, _, mocks = mock_search_service
        svc.settings.visual_embedding_enabled = False
        mocks["classify_intent"].return_value = _intent(
            "general",
            alpha=0.7,
            visual_weight=0.25,
            text_knn_weight=0.45,
            bm25_weight=0.3,
        )

        await _run_semantic_search(svc, org_id, "일반 검색")

        kwargs = mocks["compute_weighted_rrf"].call_args.kwargs
        assert kwargs["bm25_weight"] == pytest.approx(0.4, abs=1e-6)
        assert kwargs["text_knn_weight"] == pytest.approx(0.6, abs=1e-6)
        assert kwargs["visual_weight"] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_semantic_mode_always_calls_text_vector_search(self, mock_search_service, org_id):
        svc, os_client, mocks = mock_search_service
        svc.settings.visual_embedding_enabled = True
        mocks["classify_intent"].return_value = _intent(
            "metadata",
            alpha=0.0,
            visual_weight=0.0,
            text_knn_weight=0.0,
            bm25_weight=1.0,
        )

        await _run_semantic_search(svc, org_id, "3만원 할인")

        os_client.search_vector.assert_called_once()

    @pytest.mark.asyncio
    async def test_bm25_runs_when_weight_positive(self, mock_search_service, org_id):
        svc, os_client, mocks = mock_search_service
        svc.settings.visual_embedding_enabled = True
        mocks["classify_intent"].return_value = _intent(
            "general",
            alpha=0.7,
            visual_weight=0.25,
            text_knn_weight=0.45,
            bm25_weight=0.3,
        )

        await _run_semantic_search(svc, org_id, "봄 코디 추천")

        os_client.search_lexical.assert_called_once()

    @pytest.mark.asyncio
    async def test_compute_weighted_rrf_gets_empty_visual_results_when_visual_disabled(
        self, mock_search_service, org_id
    ):
        svc, _, mocks = mock_search_service
        svc.settings.visual_embedding_enabled = False
        mocks["classify_intent"].return_value = _intent(
            "visual",
            alpha=0.7,
            visual_weight=0.4,
            text_knn_weight=0.35,
            bm25_weight=0.25,
        )

        await _run_semantic_search(svc, org_id, "빨간색 원피스")

        kwargs = mocks["compute_weighted_rrf"].call_args.kwargs
        assert kwargs["visual_results"] == []
        assert kwargs["visual_weight"] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_visual_search_skipped_when_visual_embedding_is_none(self, mock_search_service, org_id):
        svc, os_client, mocks = mock_search_service
        svc.settings.visual_embedding_enabled = True
        mocks["get_visual_query_embedding"].return_value = None
        mocks["classify_intent"].return_value = _intent(
            "visual",
            alpha=0.7,
            visual_weight=0.4,
            text_knn_weight=0.35,
            bm25_weight=0.25,
        )

        await _run_semantic_search(svc, org_id, "빨간색 원피스")

        os_client.search_visual_vector.assert_not_called()
        kwargs = mocks["compute_weighted_rrf"].call_args.kwargs
        assert kwargs["visual_results"] == []
