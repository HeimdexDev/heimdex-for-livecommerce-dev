# pyright: reportUnknownParameterType=false, reportMissingParameterType=false, reportAny=false, reportUnusedCallResult=false, reportUnknownVariableType=false, reportUnknownMemberType=false
"""Tests for the moodboard page_size / max_per_video override path.

Covers:
- Schema validation (accept in-range, reject out-of-range, default None)
- `_clamp_page_size` clamping against `search_page_size_max`
- `search()` threading overrides through to `diversify_results`
- Regression guard: video-path default still uses settings.search_page_size
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.search.schemas import SearchRequest


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_search_request_defaults_page_size_to_none():
    req = SearchRequest(q="test")
    assert req.page_size is None
    assert req.max_per_video is None


def test_search_request_accepts_moodboard_override():
    req = SearchRequest(q="test", page_size=60, max_per_video=6)
    assert req.page_size == 60
    assert req.max_per_video == 6


def test_search_request_rejects_page_size_above_ceiling():
    with pytest.raises(Exception):  # pydantic ValidationError
        SearchRequest(q="test", page_size=9999)


def test_search_request_rejects_page_size_zero():
    with pytest.raises(Exception):
        SearchRequest(q="test", page_size=0)


def test_search_request_rejects_max_per_video_zero():
    with pytest.raises(Exception):
        SearchRequest(q="test", max_per_video=0)


# ---------------------------------------------------------------------------
# _clamp_page_size
# ---------------------------------------------------------------------------


def _make_service_with_settings(**overrides):
    """Build a bare SceneSearchService whose settings we control."""
    from app.modules.search.scene_service import SceneSearchService

    service = SceneSearchService.__new__(SceneSearchService)
    settings = MagicMock()
    settings.search_page_size = overrides.get("search_page_size", 20)
    settings.search_page_size_max = overrides.get("search_page_size_max", 120)
    settings.search_max_scenes_per_video = overrides.get(
        "search_max_scenes_per_video", 4
    )
    settings.search_lexical_top_k = overrides.get("search_lexical_top_k", 200)
    settings.search_vector_top_k = overrides.get("search_vector_top_k", 200)
    settings.reranker_enabled = overrides.get("reranker_enabled", False)
    settings.reranker_top_k = overrides.get("reranker_top_k", 20)
    settings.visual_embedding_enabled = overrides.get(
        "visual_embedding_enabled", False
    )
    service.settings = settings
    service.session = MagicMock()
    service.scene_opensearch = MagicMock()
    return service


def test_clamp_page_size_none_returns_default():
    svc = _make_service_with_settings(search_page_size=20)
    assert svc._clamp_page_size(None) == 20


def test_clamp_page_size_passthrough_in_range():
    svc = _make_service_with_settings()
    assert svc._clamp_page_size(60) == 60


def test_clamp_page_size_clamps_to_ceiling():
    svc = _make_service_with_settings(search_page_size_max=120)
    assert svc._clamp_page_size(9999) == 120


def test_clamp_page_size_clamps_floor():
    svc = _make_service_with_settings()
    assert svc._clamp_page_size(0) == 1
    assert svc._clamp_page_size(-5) == 1


# ---------------------------------------------------------------------------
# search() threads overrides to diversify_results
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_lexical_threads_moodboard_override_to_diversify():
    """page_size=60, max_per_video=6 must reach diversify_results unchanged."""
    from app.modules.search.scene_service import SceneSearchService, _SearchContext
    from app.modules.search.schemas import SearchFilters

    svc = _make_service_with_settings()
    svc._prepare_search_context = AsyncMock(
        return_value=_SearchContext(
            query="pink dress",
            org_id=uuid4(),
            org_id_str="org",
            filter_dict={"content_types": ["image"]},
            matched_person_cluster_ids=[],
            people_label_map={},
            library_map={},
            facet_data={},
            include_ocr=None,
            group_by="scene",
        )
    )
    svc.scene_opensearch.search_lexical = AsyncMock(return_value=[])
    svc._build_scene_results = MagicMock(return_value=[])
    from app.modules.search.schemas import Facets
    svc._build_facets = MagicMock(return_value=Facets())
    svc._backfill_web_view_links = AsyncMock()

    with patch(
        "app.modules.search.scene_service.diversify_results",
        return_value=[],
    ) as mock_diversify:
        await svc.search(
            query="pink dress",
            org_id=uuid4(),
            alpha=0.5,
            filters=SearchFilters(content_types=["image"]),
            search_mode="lexical",
            page_size=60,
            max_per_video=6,
        )

    mock_diversify.assert_called_once()
    _, kwargs = mock_diversify.call_args
    assert kwargs["target_count"] == 60
    assert kwargs["max_per_video"] == 6


@pytest.mark.asyncio
async def test_search_lexical_default_video_path_still_20():
    """Regression guard: when no override, diversify gets settings defaults."""
    from app.modules.search.scene_service import SceneSearchService, _SearchContext
    from app.modules.search.schemas import SearchFilters

    svc = _make_service_with_settings(
        search_page_size=20, search_max_scenes_per_video=4
    )
    svc._prepare_search_context = AsyncMock(
        return_value=_SearchContext(
            query="test",
            org_id=uuid4(),
            org_id_str="org",
            filter_dict={"content_types": ["video"]},
            matched_person_cluster_ids=[],
            people_label_map={},
            library_map={},
            facet_data={},
            include_ocr=None,
            group_by="scene",
        )
    )
    svc.scene_opensearch.search_lexical = AsyncMock(return_value=[])
    svc._build_scene_results = MagicMock(return_value=[])
    from app.modules.search.schemas import Facets
    svc._build_facets = MagicMock(return_value=Facets())
    svc._backfill_web_view_links = AsyncMock()

    with patch(
        "app.modules.search.scene_service.diversify_results",
        return_value=[],
    ) as mock_diversify:
        await svc.search(
            query="test",
            org_id=uuid4(),
            alpha=0.5,
            filters=SearchFilters(content_types=["video"]),
            search_mode="lexical",
        )

    _, kwargs = mock_diversify.call_args
    assert kwargs["target_count"] == 20
    assert kwargs["max_per_video"] == 4


@pytest.mark.asyncio
async def test_search_semantic_threads_moodboard_override_to_diversify():
    """Semantic mode must also honor page_size/max_per_video overrides.

    Regression guard: my moodboard change touches all three mode methods;
    this confirms _search_semantic's diversify_results call uses the
    per-request overrides, not settings defaults.
    """
    from app.modules.search.scene_service import _SearchContext
    from app.modules.search.schemas import Facets, SearchFilters

    svc = _make_service_with_settings(visual_embedding_enabled=False)
    svc._prepare_search_context = AsyncMock(
        return_value=_SearchContext(
            query="pink dress",
            org_id=uuid4(),
            org_id_str="org",
            filter_dict={"content_types": ["image"]},
            matched_person_cluster_ids=[],
            people_label_map={},
            library_map={},
            facet_data={},
            include_ocr=None,
            group_by="scene",
        )
    )
    svc.scene_opensearch.search_lexical = AsyncMock(return_value=[])
    svc.scene_opensearch.search_vector = AsyncMock(return_value=[])
    svc.scene_opensearch.search_visual_vector = AsyncMock(return_value=[])
    svc.scene_opensearch.search_color_vector = AsyncMock(return_value=[])
    svc._build_scene_results = MagicMock(return_value=[])
    svc._build_facets = MagicMock(return_value=Facets())
    svc._backfill_web_view_links = AsyncMock()

    # Mock embedding generators so no real model is loaded
    with patch(
        "app.modules.search.scene_service.get_query_embedding",
        new=AsyncMock(return_value=[0.1] * 1024),
    ), patch(
        "app.modules.search.scene_service.diversify_results",
        return_value=[],
    ) as mock_diversify:
        await svc.search(
            query="pink dress",
            org_id=uuid4(),
            alpha=0.5,
            filters=SearchFilters(content_types=["image"]),
            search_mode="semantic",
            page_size=60,
            max_per_video=6,
        )

    mock_diversify.assert_called_once()
    _, kwargs = mock_diversify.call_args
    assert kwargs["target_count"] == 60
    assert kwargs["max_per_video"] == 6


@pytest.mark.asyncio
async def test_search_metadata_threads_moodboard_override_to_diversify():
    """Metadata mode (file-title / source-path BM25) must also honor overrides."""
    from app.modules.search.scene_service import _SearchContext
    from app.modules.search.schemas import Facets, SearchFilters

    svc = _make_service_with_settings()
    svc._prepare_search_context = AsyncMock(
        return_value=_SearchContext(
            query="vacation",
            org_id=uuid4(),
            org_id_str="org",
            filter_dict={"content_types": ["image"]},
            matched_person_cluster_ids=[],
            people_label_map={},
            library_map={},
            facet_data={},
            include_ocr=None,
            group_by="video",
        )
    )
    svc.scene_opensearch.search_metadata = AsyncMock(return_value=[])
    svc._build_scene_results = MagicMock(return_value=[])
    svc._build_facets = MagicMock(return_value=Facets())
    svc._backfill_web_view_links = AsyncMock()

    with patch(
        "app.modules.search.scene_service.diversify_results",
        return_value=[],
    ) as mock_diversify:
        await svc.search(
            query="vacation",
            org_id=uuid4(),
            alpha=0.5,
            filters=SearchFilters(content_types=["image"]),
            search_mode="metadata",
            page_size=60,
            max_per_video=6,
        )

    _, kwargs = mock_diversify.call_args
    assert kwargs["target_count"] == 60
    assert kwargs["max_per_video"] == 6


@pytest.mark.asyncio
async def test_search_clamps_absurd_page_size_at_service_layer():
    """Defense in depth: a direct service caller bypassing Pydantic is still clamped."""
    from app.modules.search.scene_service import SceneSearchService, _SearchContext
    from app.modules.search.schemas import SearchFilters

    svc = _make_service_with_settings(search_page_size_max=120)
    svc._prepare_search_context = AsyncMock(
        return_value=_SearchContext(
            query="test",
            org_id=uuid4(),
            org_id_str="org",
            filter_dict={},
            matched_person_cluster_ids=[],
            people_label_map={},
            library_map={},
            facet_data={},
            include_ocr=None,
            group_by="scene",
        )
    )
    svc.scene_opensearch.search_lexical = AsyncMock(return_value=[])
    svc._build_scene_results = MagicMock(return_value=[])
    from app.modules.search.schemas import Facets
    svc._build_facets = MagicMock(return_value=Facets())
    svc._backfill_web_view_links = AsyncMock()

    with patch(
        "app.modules.search.scene_service.diversify_results",
        return_value=[],
    ) as mock_diversify:
        await svc.search(
            query="test",
            org_id=uuid4(),
            alpha=0.5,
            filters=SearchFilters(),
            search_mode="lexical",
            page_size=99999,
        )

    _, kwargs = mock_diversify.call_args
    assert kwargs["target_count"] == 120
