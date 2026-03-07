# pyright: reportUnknownParameterType=false, reportMissingParameterType=false, reportAny=false, reportUnusedCallResult=false, reportUnknownVariableType=false, reportUnknownMemberType=false

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.ingest.schemas import IngestSceneDocument, IngestScenesRequest
from app.modules.ingest.service import SceneIngestService
from app.modules.search.schemas import DebugInfo, Facets, SceneResult, SearchFilters


@pytest.fixture
def mock_scene_client():
    with patch("app.modules.search.scene_client.get_settings") as mock_settings, patch(
        "app.modules.search.scene_client.get_opensearch_client"
    ) as mock_get_client:
        settings = MagicMock()
        settings.opensearch_url = "http://localhost:9200"
        settings.opensearch_index_prefix = "test"
        settings.opensearch_facet_size = 100
        mock_settings.return_value = settings

        async_client = MagicMock()
        async_client.indices = MagicMock()
        async_client.close = AsyncMock()
        mock_get_client.return_value = async_client

        from app.modules.search.scene_client import SceneSearchClient

        client = SceneSearchClient()
        client.client = async_client
        yield client, async_client


def _make_debug_info() -> DebugInfo:
    return DebugInfo(fused_score=1.0, adjusted_score=1.0)


def test_search_filters_default_content_types() -> None:
    filters = SearchFilters()
    assert filters.content_types == ["video"]


def test_search_filters_custom_content_types() -> None:
    filters = SearchFilters(content_types=["image"])
    assert filters.content_types == ["image"]


def test_search_filters_both_content_types() -> None:
    filters = SearchFilters(content_types=["video", "image"])
    assert filters.content_types == ["video", "image"]


def test_build_filter_clauses_includes_content_type(mock_scene_client) -> None:
    client, _ = mock_scene_client
    clauses, must_not = client._build_filter_clauses({"content_types": ["video"]})

    assert must_not == []
    assert {"terms": {"content_type": ["video"]}} in clauses


def test_build_filter_clauses_default_content_type_from_search_filters(mock_scene_client) -> None:
    client, _ = mock_scene_client
    filters = SearchFilters()

    clauses, must_not = client._build_filter_clauses(filters.model_dump())

    assert must_not == []
    assert {"terms": {"content_type": ["video"]}} in clauses


def test_scene_result_defaults_content_type_and_image_width() -> None:
    result = SceneResult(
        scene_id="scene_1",
        video_id="video_1",
        library_id=uuid4(),
        library_name="Library",
        start_ms=0,
        end_ms=1000,
        snippet="snippet",
        thumbnail_url=None,
        source_type="gdrive",
        debug=_make_debug_info(),
    )

    assert result.content_type == "video"
    assert result.image_width is None


def test_scene_result_image_fields() -> None:
    result = SceneResult(
        scene_id="scene_1",
        video_id="video_1",
        library_id=uuid4(),
        library_name="Library",
        start_ms=0,
        end_ms=1000,
        snippet="snippet",
        thumbnail_url=None,
        source_type="gdrive",
        content_type="image",
        image_width=1920,
        image_height=1080,
        image_orientation="landscape",
        debug=_make_debug_info(),
    )

    assert result.content_type == "image"
    assert result.image_width == 1920
    assert result.image_height == 1080
    assert result.image_orientation == "landscape"


def test_facets_content_types_default_empty_list() -> None:
    facets = Facets()
    assert facets.content_types == []


@pytest.mark.asyncio
async def test_ingest_doc_builder_includes_content_type_key() -> None:
    mock_db_session = AsyncMock()
    mock_scene_opensearch = MagicMock()
    mock_scene_opensearch.bulk_index_scenes = AsyncMock()
    service = SceneIngestService(mock_db_session, mock_scene_opensearch)

    org_id = uuid4()
    library_id = uuid4()
    scene = IngestSceneDocument(
        scene_id="img_1_scene_0",
        index=0,
        start_ms=0,
        end_ms=1000,
        transcript_raw="",
        content_type="image",
        image_width=1920,
    )
    request = IngestScenesRequest(
        video_id="img_1",
        library_id=library_id,
        scenes=[scene],
    )

    mock_library = MagicMock()
    mock_library.id = library_id
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_library
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    await service.ingest_scenes(request, org_id)

    docs = mock_scene_opensearch.bulk_index_scenes.call_args[0][0]
    _, doc = docs[0]

    assert "content_type" in doc
    assert doc["content_type"] == "image"
    assert doc["image_width"] == 1920


@pytest.mark.asyncio
async def test_aggregate_videos_always_filters_video_content_type(mock_scene_client) -> None:
    client, mock_async = mock_scene_client
    mock_async.search = AsyncMock(
        return_value={
            "aggregations": {
                "videos": {"buckets": []},
                "total_videos": {"value": 0},
                "facet_libraries": {"buckets": []},
                "facet_source_types": {"buckets": []},
            }
        }
    )

    await client.aggregate_videos("org-1")

    call_body = mock_async.search.call_args.kwargs["body"]
    filters = call_body["query"]["bool"]["filter"]
    assert {"term": {"content_type": "video"}} in filters


@pytest.mark.asyncio
async def test_get_video_stats_always_filters_video_content_type(mock_scene_client) -> None:
    client, mock_async = mock_scene_client
    mock_async.search = AsyncMock(
        return_value={
            "hits": {"total": {"value": 0}},
            "aggregations": {
                "total_videos": {"value": 0},
                "total_libraries": {"value": 0},
                "source_breakdown": {"buckets": []},
                "latest_ingest": {"value": None, "value_as_string": None},
                "latest_capture": {"value": None, "value_as_string": None},
                "scenes_last_24h": {"doc_count": 0},
                "scenes_last_7d": {"doc_count": 0},
            },
        }
    )

    await client.get_video_stats("org-1")

    call_body = mock_async.search.call_args.kwargs["body"]
    filters = call_body["query"]["bool"]["filter"]
    assert {"term": {"content_type": "video"}} in filters


@pytest.mark.asyncio
async def test_get_videos_by_person_always_filters_video_content_type(mock_scene_client) -> None:
    client, mock_async = mock_scene_client
    mock_async.search = AsyncMock(return_value={"aggregations": {"by_video": {"buckets": []}}})

    await client.get_videos_by_person("org-1", "cluster-1")

    call_body = mock_async.search.call_args.kwargs["body"]
    filters = call_body["query"]["bool"]["filter"]
    assert {"term": {"content_type": "video"}} in filters
