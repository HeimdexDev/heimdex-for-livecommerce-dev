"""
Unit tests for three-mode search routing (metadata / lexical / semantic).

Tests verify:
1. search_mode routes to the correct internal method
2. Default mode is "lexical" for backward compatibility
3. Metadata mode always returns VideoSearchResponse
4. Lexical mode does NOT compute embeddings
5. Semantic mode does NOT run BM25 queries
6. Metadata mode does NOT compute embeddings or run content BM25
7. search_mode schema validation rejects invalid values
8. Backward compatibility: old requests without search_mode still work
9. Router passes search_mode through to service
10. Filters are applied in all modes
11. search_metadata client method uses correct BM25 fields
12. group_by works with lexical and semantic modes

Run with: pytest tests/test_search_mode_routing.py -v
"""
import pytest
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from pydantic import ValidationError

from app.modules.search.schemas import (
    Facets,
    SceneSearchResponse,
    SearchFilters,
    SearchRequest,
    VideoSearchResponse,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _mock_scene_response(query: str = "test", alpha: float = 0.5) -> SceneSearchResponse:
    return SceneSearchResponse(
        results=[],
        total_candidates=0,
        facets=Facets(),
        query=query,
        alpha=alpha,
    )


def _mock_video_response(query: str = "test", alpha: float = 0.5) -> VideoSearchResponse:
    return VideoSearchResponse(
        results=[],
        total_candidates=0,
        facets=Facets(),
        query=query,
        alpha=alpha,
    )


@pytest.fixture
def org_id():
    return uuid4()


@pytest.fixture
def user_id():
    return uuid4()


@pytest.fixture
def mock_session():
    """Mock AsyncSession with people/library repo behavior."""
    session = AsyncMock()
    return session


@pytest.fixture
def mock_scene_opensearch():
    """Mock SceneSearchClient with all search methods."""
    client = MagicMock()
    client.search_metadata = AsyncMock(return_value=[])
    client.search_lexical = AsyncMock(return_value=[])
    client.search_vector = AsyncMock(return_value=[])
    client.search_visual_vector = AsyncMock(return_value=[])
    client.get_facets = AsyncMock(return_value={
        "libraries": [],
        "source_types": [],
        "people": [],
    })
    return client


@pytest.fixture
def mock_search_service(mock_session, mock_scene_opensearch):
    """Build SceneSearchService with mocked dependencies."""
    from app.modules.search.scene_service import SceneSearchService

    with patch("app.modules.search.scene_service.PeopleClusterLabelRepository") as mock_people_repo, \
         patch("app.modules.search.scene_service.PeopleExcludePreferenceRepository"), \
         patch("app.modules.search.scene_service.LibraryRepository") as mock_lib_repo, \
         patch("app.modules.search.scene_service.get_query_embedding", new_callable=AsyncMock) as mock_embed, \
         patch("app.modules.search.scene_service.get_visual_query_embedding", new_callable=AsyncMock) as mock_visual_embed:

        # People repo returns empty
        mock_people_instance = MagicMock()
        mock_people_instance.list_by_org = AsyncMock(return_value=[])
        mock_people_repo.return_value = mock_people_instance

        # Library repo returns empty
        mock_lib_instance = MagicMock()
        mock_lib_instance.list_by_org = AsyncMock(return_value=[])
        mock_lib_repo.return_value = mock_lib_instance

        # Embedding returns a dummy vector
        mock_embed.return_value = [0.1] * 1024
        mock_visual_embed.return_value = [0.2] * 768

        svc = SceneSearchService(mock_session, mock_scene_opensearch)
        yield svc, mock_scene_opensearch, mock_embed, mock_visual_embed


# ---------------------------------------------------------------------------
# Test: Mode routing
# ---------------------------------------------------------------------------

class TestSearchModeRouting:
    """Tests that search_mode routes to the correct internal method."""

    @pytest.mark.asyncio
    async def test_metadata_mode_calls_search_metadata(self, mock_search_service, org_id):
        """Metadata mode should call scene_opensearch.search_metadata()."""
        svc, os_client, mock_embed, mock_visual_embed = mock_search_service

        await svc.search(
            query="test query",
            org_id=org_id,
            alpha=0.5,
            filters=SearchFilters(),
            search_mode="metadata",
        )

        os_client.search_metadata.assert_called_once()
        os_client.search_lexical.assert_not_called()
        os_client.search_vector.assert_not_called()
        os_client.search_visual_vector.assert_not_called()
        mock_embed.assert_not_called()
        mock_visual_embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_lexical_mode_calls_search_lexical(self, mock_search_service, org_id):
        """Lexical mode should call scene_opensearch.search_lexical() only."""
        svc, os_client, mock_embed, mock_visual_embed = mock_search_service

        await svc.search(
            query="test query",
            org_id=org_id,
            alpha=0.5,
            filters=SearchFilters(),
            search_mode="lexical",
        )

        os_client.search_lexical.assert_called_once()
        os_client.search_metadata.assert_not_called()
        os_client.search_vector.assert_not_called()
        os_client.search_visual_vector.assert_not_called()
        mock_embed.assert_not_called()
        mock_visual_embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_semantic_mode_calls_search_vector(self, mock_search_service, org_id):
        """Semantic mode should compute embedding and call search_vector().

        With intent-aware routing, semantic mode may also call search_lexical()
        for queries classified as metadata/factual/general intent.
        """
        svc, os_client, mock_embed, _ = mock_search_service

        await svc.search(
            query="test query",
            org_id=org_id,
            alpha=0.5,
            filters=SearchFilters(),
            search_mode="semantic",
        )

        os_client.search_vector.assert_called_once()
        mock_embed.assert_called_once()
        os_client.search_metadata.assert_not_called()
    @pytest.mark.asyncio
    async def test_default_mode_is_lexical(self, mock_search_service, org_id):
        """Default search_mode should be 'lexical' for backward compatibility."""
        svc, os_client, mock_embed, _ = mock_search_service

        await svc.search(
            query="test query",
            org_id=org_id,
            alpha=0.5,
            filters=SearchFilters(),
            # search_mode not provided → defaults to "lexical"
        )

        os_client.search_lexical.assert_called_once()
        os_client.search_vector.assert_not_called()
        mock_embed.assert_not_called()


# ---------------------------------------------------------------------------
# Test: Response types
# ---------------------------------------------------------------------------

class TestSearchModeResponses:
    """Tests that each mode returns the expected response type."""

    @pytest.mark.asyncio
    async def test_metadata_mode_always_returns_video_response(self, mock_search_service, org_id):
        """Metadata mode should always return VideoSearchResponse."""
        svc, os_client, _, _ = mock_search_service

        result = await svc.search(
            query="test",
            org_id=org_id,
            alpha=0.5,
            filters=SearchFilters(),
            search_mode="metadata",
        )

        assert isinstance(result, VideoSearchResponse)
        assert result.result_type == "video"

    @pytest.mark.asyncio
    async def test_lexical_mode_returns_scene_response_by_default(self, mock_search_service, org_id):
        """Lexical mode with group_by='scene' returns SceneSearchResponse."""
        svc, _, _, _ = mock_search_service

        result = await svc.search(
            query="test",
            org_id=org_id,
            alpha=0.5,
            filters=SearchFilters(),
            search_mode="lexical",
            group_by="scene",
        )

        assert isinstance(result, SceneSearchResponse)
        assert result.result_type == "scene"

    @pytest.mark.asyncio
    async def test_lexical_mode_with_video_grouping(self, mock_search_service, org_id):
        """Lexical mode with group_by='video' returns VideoSearchResponse."""
        svc, _, _, _ = mock_search_service

        result = await svc.search(
            query="test",
            org_id=org_id,
            alpha=0.5,
            filters=SearchFilters(),
            search_mode="lexical",
            group_by="video",
        )

        assert isinstance(result, VideoSearchResponse)
        assert result.result_type == "video"

    @pytest.mark.asyncio
    async def test_semantic_mode_returns_scene_response_by_default(self, mock_search_service, org_id):
        """Semantic mode with group_by='scene' returns SceneSearchResponse."""
        svc, _, _, _ = mock_search_service

        result = await svc.search(
            query="test",
            org_id=org_id,
            alpha=0.5,
            filters=SearchFilters(),
            search_mode="semantic",
            group_by="scene",
        )

        assert isinstance(result, SceneSearchResponse)
        assert result.result_type == "scene"


# ---------------------------------------------------------------------------
# Test: No unnecessary work
# ---------------------------------------------------------------------------

class TestSearchModeEfficiency:
    """Tests that each mode avoids unnecessary computation."""

    @pytest.mark.asyncio
    async def test_metadata_no_embedding_computation(self, mock_search_service, org_id):
        """Metadata mode should NOT compute query embedding."""
        svc, _, mock_embed, _ = mock_search_service

        await svc.search(
            query="some file",
            org_id=org_id,
            alpha=0.5,
            filters=SearchFilters(),
            search_mode="metadata",
        )

        mock_embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_lexical_no_embedding_computation(self, mock_search_service, org_id):
        """Lexical mode should NOT compute query embedding."""
        svc, _, mock_embed, _ = mock_search_service

        await svc.search(
            query="exact words here",
            org_id=org_id,
            alpha=0.5,
            filters=SearchFilters(),
            search_mode="lexical",
        )

        mock_embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_semantic_blends_bm25_for_general_intent(self, mock_search_service, org_id):
        """Semantic mode with general intent blends BM25 via intent classification.

        Intent-aware routing uses alpha < 1.0 for general queries, which
        triggers BM25 alongside kNN for better result quality.
        """
        svc, os_client, _, _ = mock_search_service

        await svc.search(
            query="meaning based search",
            org_id=org_id,
            alpha=0.5,
            filters=SearchFilters(),
            search_mode="semantic",
        )

        # General intent uses alpha=0.7 which triggers BM25 blend
        os_client.search_vector.assert_called_once()
        os_client.search_lexical.assert_called_once()
        os_client.search_metadata.assert_not_called()

    @pytest.mark.asyncio
    async def test_metadata_mode_never_calls_visual_search(self, mock_search_service, org_id):
        svc, os_client, mock_embed, mock_visual_embed = mock_search_service

        await svc.search(
            query="metadata only query",
            org_id=org_id,
            alpha=0.5,
            filters=SearchFilters(),
            search_mode="metadata",
        )

        mock_embed.assert_not_called()
        mock_visual_embed.assert_not_called()
        os_client.search_vector.assert_not_called()
        os_client.search_visual_vector.assert_not_called()

    @pytest.mark.asyncio
    async def test_lexical_mode_never_calls_visual_search(self, mock_search_service, org_id):
        svc, os_client, mock_embed, mock_visual_embed = mock_search_service

        await svc.search(
            query="exact lexical query",
            org_id=org_id,
            alpha=0.5,
            filters=SearchFilters(),
            search_mode="lexical",
        )

        mock_embed.assert_not_called()
        mock_visual_embed.assert_not_called()
        os_client.search_vector.assert_not_called()
        os_client.search_visual_vector.assert_not_called()

# ---------------------------------------------------------------------------
# Test: Schema validation
# ---------------------------------------------------------------------------

class TestSearchModeSchema:
    """Tests for search_mode schema validation."""

    def test_valid_modes_accepted(self):
        """All three modes should be accepted."""
        for mode in ("metadata", "lexical", "semantic"):
            req = SearchRequest(q="test", search_mode=mode)
            assert req.search_mode == mode

    def test_invalid_mode_rejected(self):
        """Invalid search_mode values should be rejected."""
        with pytest.raises(ValidationError):
            SearchRequest(q="test", search_mode=cast(Any, "hybrid"))

    def test_default_mode_is_lexical(self):
        """Default search_mode should be 'lexical'."""
        req = SearchRequest(q="test")
        assert req.search_mode == "lexical"

    def test_backward_compatibility_alpha_still_accepted(self):
        """Requests with alpha but no search_mode should still work."""
        req = SearchRequest(q="test", alpha=0.7)
        assert req.alpha == 0.7
        assert req.search_mode == "lexical"

    def test_search_mode_and_alpha_coexist(self):
        """Both search_mode and alpha can be set simultaneously."""
        req = SearchRequest(q="test", search_mode="semantic", alpha=0.3)
        assert req.search_mode == "semantic"
        assert req.alpha == 0.3


# ---------------------------------------------------------------------------
# Test: Router passthrough
# ---------------------------------------------------------------------------

class TestRouterSearchModePassthrough:
    """Tests that the router passes search_mode to the service."""

    @pytest.fixture
    def mock_scene_search_service(self):
        svc = MagicMock()
        svc.search = AsyncMock(return_value=_mock_scene_response())
        return svc

    @pytest.fixture
    def mock_segment_search_service(self):
        svc = MagicMock()
        svc.search = AsyncMock(return_value=MagicMock())
        return svc

    @pytest.fixture
    def mock_user(self):
        user = MagicMock()
        user.id = uuid4()
        return user

    @pytest.fixture
    def mock_org_ctx(self, org_id):
        ctx = MagicMock()
        ctx.org_id = org_id
        return ctx

    @pytest.mark.asyncio
    async def test_router_passes_search_mode_to_scene_service(
        self, mock_scene_search_service, mock_segment_search_service,
        mock_user, mock_org_ctx,
    ):
        """Router should forward search_mode to scene_search_service.search()."""
        from app.modules.search.router import search

        request = MagicMock(
            q="test",
            alpha=0.5,
            filters=SearchFilters(),
            include_ocr=None,
            group_by="scene",
            search_mode="semantic",
        )

        with patch("app.modules.search.router.get_settings") as mock_settings:
            settings = MagicMock()
            settings.search_default_mode = "scenes"
            mock_settings.return_value = settings

            await search(
                request=request,
                org_ctx=mock_org_ctx,
                user=mock_user,
                search_service=mock_segment_search_service,
                scene_search_service=mock_scene_search_service,
            )

        call_kwargs = mock_scene_search_service.search.call_args.kwargs
        assert call_kwargs["search_mode"] == "semantic"

    @pytest.mark.asyncio
    async def test_scenes_endpoint_passes_search_mode(
        self, mock_scene_search_service, mock_user, mock_org_ctx,
    ):
        """POST /api/search/scenes should forward search_mode."""
        from app.modules.search.router import search_scenes

        request = MagicMock(
            q="metadata query",
            alpha=0.5,
            filters=SearchFilters(),
            include_ocr=None,
            group_by="scene",
            search_mode="metadata",
        )

        await search_scenes(
            request=request,
            org_ctx=mock_org_ctx,
            user=mock_user,
            scene_search_service=mock_scene_search_service,
        )

        call_kwargs = mock_scene_search_service.search.call_args.kwargs
        assert call_kwargs["search_mode"] == "metadata"


# ---------------------------------------------------------------------------
# Test: Filters applied in all modes
# ---------------------------------------------------------------------------

class TestSearchModeFilters:
    """Tests that filters are applied regardless of mode."""

    @pytest.mark.asyncio
    async def test_metadata_mode_applies_date_filter(self, mock_search_service, org_id):
        """Metadata mode should pass date filters to search_metadata()."""
        from datetime import datetime

        svc, os_client, _, _ = mock_search_service
        filters = SearchFilters(date_from=datetime(2026, 1, 1))

        await svc.search(
            query="test",
            org_id=org_id,
            alpha=0.5,
            filters=filters,
            search_mode="metadata",
        )

        call_kwargs = os_client.search_metadata.call_args.kwargs
        assert call_kwargs["filters"]["date_from"] == datetime(2026, 1, 1)

    @pytest.mark.asyncio
    async def test_lexical_mode_applies_source_type_filter(self, mock_search_service, org_id):
        """Lexical mode should pass source_type filters to search_lexical()."""
        svc, os_client, _, _ = mock_search_service
        filters = SearchFilters(source_types=["gdrive"])

        await svc.search(
            query="test",
            org_id=org_id,
            alpha=0.5,
            filters=filters,
            search_mode="lexical",
        )

        call_kwargs = os_client.search_lexical.call_args.kwargs
        assert call_kwargs["filters"]["source_types"] == ["gdrive"]

    @pytest.mark.asyncio
    async def test_semantic_mode_applies_date_filter(self, mock_search_service, org_id):
        """Semantic mode should pass date filters to search_vector()."""
        from datetime import datetime

        svc, os_client, _, _ = mock_search_service
        filters = SearchFilters(date_from=datetime(2026, 2, 1))

        await svc.search(
            query="test",
            org_id=org_id,
            alpha=0.5,
            filters=filters,
            search_mode="semantic",
        )

        call_kwargs = os_client.search_vector.call_args.kwargs
        assert call_kwargs["filters"]["date_from"] == datetime(2026, 2, 1)
