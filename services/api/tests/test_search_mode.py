"""
Unit tests for config-gated search routing.

Tests verify:
1. POST /api/search with SEARCH_DEFAULT_MODE=segments returns SegmentResult (SearchResponse)
2. POST /api/search with SEARCH_DEFAULT_MODE=scenes returns SceneResult (SceneSearchResponse)
3. POST /api/search/scenes always returns SceneSearchResponse regardless of mode
4. SearchResponse has result_type="segment"
5. SceneSearchResponse has result_type="scene"

Run with: pytest tests/test_search_mode.py -v
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.modules.search.schemas import (
    Facets,
    SceneSearchResponse,
    SearchFilters,
    SearchResponse,
)


def _mock_segment_response(query: str = "test", alpha: float = 0.5) -> SearchResponse:
    """Build a minimal SearchResponse for mocking."""
    return SearchResponse(
        results=[],
        total_candidates=0,
        facets=Facets(),
        query=query,
        alpha=alpha,
    )


def _mock_scene_response(query: str = "test", alpha: float = 0.5) -> SceneSearchResponse:
    """Build a minimal SceneSearchResponse for mocking."""
    return SceneSearchResponse(
        results=[],
        total_candidates=0,
        facets=Facets(),
        query=query,
        alpha=alpha,
    )


class TestSearchModeRouting:
    """Tests for POST /api/search config-gated routing."""

    @pytest.fixture
    def org_id(self):
        return uuid4()

    @pytest.fixture
    def mock_search_service(self):
        svc = MagicMock()
        svc.search = AsyncMock(return_value=_mock_segment_response())
        return svc

    @pytest.fixture
    def mock_scene_search_service(self):
        svc = MagicMock()
        svc.search = AsyncMock(return_value=_mock_scene_response())
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

    # ------------------------------------------------------------------
    # POST /api/search — default mode (segments)
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_default_mode_routes_to_segment_search(
        self, mock_search_service, mock_scene_search_service, mock_user, mock_org_ctx
    ):
        """With SEARCH_DEFAULT_MODE=segments (default), /api/search calls SearchService."""
        from app.modules.search.router import search

        with patch("app.modules.search.router.get_settings") as mock_settings:
            settings = MagicMock()
            settings.search_default_mode = "segments"
            mock_settings.return_value = settings

            result = await search(
                request=MagicMock(q="test", alpha=0.5, filters=SearchFilters()),
                org_ctx=mock_org_ctx,
                user=mock_user,
                search_service=mock_search_service,
                scene_search_service=mock_scene_search_service,
            )

        mock_search_service.search.assert_called_once()
        mock_scene_search_service.search.assert_not_called()
        assert isinstance(result, SearchResponse)
        assert result.result_type == "segment"

    # ------------------------------------------------------------------
    # POST /api/search — scenes mode
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_scenes_mode_routes_to_scene_search(
        self, mock_search_service, mock_scene_search_service, mock_user, mock_org_ctx
    ):
        """With SEARCH_DEFAULT_MODE=scenes, /api/search calls SceneSearchService."""
        from app.modules.search.router import search

        with patch("app.modules.search.router.get_settings") as mock_settings:
            settings = MagicMock()
            settings.search_default_mode = "scenes"
            mock_settings.return_value = settings

            result = await search(
                request=MagicMock(q="test", alpha=0.5, filters=SearchFilters()),
                org_ctx=mock_org_ctx,
                user=mock_user,
                search_service=mock_search_service,
                scene_search_service=mock_scene_search_service,
            )

        mock_scene_search_service.search.assert_called_once()
        mock_search_service.search.assert_not_called()
        assert isinstance(result, SceneSearchResponse)
        assert result.result_type == "scene"

    # ------------------------------------------------------------------
    # POST /api/search/scenes — always scenes
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_search_scenes_endpoint_always_returns_scenes(
        self, mock_scene_search_service, mock_user, mock_org_ctx
    ):
        """POST /api/search/scenes always calls SceneSearchService regardless of mode."""
        from app.modules.search.router import search_scenes

        # Even with segments mode, /search/scenes should use scene service
        result = await search_scenes(
            request=MagicMock(q="test", alpha=0.5, filters=SearchFilters()),
            org_ctx=mock_org_ctx,
            user=mock_user,
            scene_search_service=mock_scene_search_service,
        )

        mock_scene_search_service.search.assert_called_once()
        assert isinstance(result, SceneSearchResponse)
        assert result.result_type == "scene"

    # ------------------------------------------------------------------
    # Result type discrimination
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_segment_response_has_segment_result_type(self):
        """SearchResponse should always have result_type='segment'."""
        resp = _mock_segment_response()
        assert resp.result_type == "segment"

    @pytest.mark.asyncio
    async def test_scene_response_has_scene_result_type(self):
        """SceneSearchResponse should always have result_type='scene'."""
        resp = _mock_scene_response()
        assert resp.result_type == "scene"

    # ------------------------------------------------------------------
    # Mode passthrough: correct args forwarded
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_search_forwards_correct_args_to_scene_service(
        self, mock_search_service, mock_scene_search_service, mock_user, mock_org_ctx
    ):
        """Arguments should be correctly forwarded to SceneSearchService.search()."""
        from app.modules.search.router import search

        filters = SearchFilters(source_types=["gdrive"])
        request = MagicMock(q="my query", alpha=0.7, filters=filters)

        with patch("app.modules.search.router.get_settings") as mock_settings:
            settings = MagicMock()
            settings.search_default_mode = "scenes"
            mock_settings.return_value = settings

            await search(
                request=request,
                org_ctx=mock_org_ctx,
                user=mock_user,
                search_service=mock_search_service,
                scene_search_service=mock_scene_search_service,
            )

        call_kwargs = mock_scene_search_service.search.call_args.kwargs
        assert call_kwargs["query"] == "my query"
        assert call_kwargs["alpha"] == 0.7
        assert call_kwargs["org_id"] == mock_org_ctx.org_id
        assert call_kwargs["filters"].source_types == ["gdrive"]

    @pytest.mark.asyncio
    async def test_search_forwards_correct_args_to_segment_service(
        self, mock_search_service, mock_scene_search_service, mock_user, mock_org_ctx
    ):
        """Arguments should be correctly forwarded to SearchService.search()."""
        from app.modules.search.router import search

        filters = SearchFilters(library_ids=[uuid4()])
        request = MagicMock(q="segment query", alpha=0.3, filters=filters)

        with patch("app.modules.search.router.get_settings") as mock_settings:
            settings = MagicMock()
            settings.search_default_mode = "segments"
            mock_settings.return_value = settings

            await search(
                request=request,
                org_ctx=mock_org_ctx,
                user=mock_user,
                search_service=mock_search_service,
                scene_search_service=mock_scene_search_service,
            )

        call_kwargs = mock_search_service.search.call_args.kwargs
        assert call_kwargs["query"] == "segment query"
        assert call_kwargs["alpha"] == 0.3
        assert call_kwargs["org_id"] == mock_org_ctx.org_id
