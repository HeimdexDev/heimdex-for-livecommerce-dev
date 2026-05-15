# pyright: reportUnknownParameterType=false, reportMissingParameterType=false, reportAny=false, reportUnusedCallResult=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportOptionalSubscript=false, reportIndexIssue=false

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.videos.schemas import VideoSummary


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


def _make_aggregate_response(video_id: str, content_type: str = "video"):
    return {
        "aggregations": {
            "videos": {
                "buckets": [
                    {
                        "key": {"video_id": video_id},
                        "scene_count": {"value": 3},
                        "min_start_ms": {"value": 0},
                        "max_end_ms": {"value": 30000},
                        "earliest_ingest": {"value": 1700000000, "value_as_string": "2024-01-01T00:00:00Z"},
                        "latest_ingest": {"value": 1700000000, "value_as_string": "2024-01-01T00:00:00Z"},
                        "min_keyframe_ms": {"value": 0},
                        "library_id": {"buckets": [{"key": "lib-1"}]},
                        "video_title": {"buckets": [{"key": "test.mp4"}]},
                        "source_type": {"buckets": [{"key": "gdrive"}]},
                        "required_drive_nickname": {"buckets": []},
                        "web_view_link": {"buckets": []},
                        "content_type": {"buckets": [{"key": content_type}]},
                        "source_path": {"buckets": []},
                        "keyword_tags": {"buckets": []},
                        "product_tags": {"buckets": []},
                        "people_count": {"value": 0},
                        "earliest_capture": {"value": None},
                    }
                ],
                "after_key": None,
            },
            "total_videos": {"value": 1},
            "facet_libraries": {"buckets": []},
            "facet_source_types": {"buckets": []},
        }
    }


# ---------------------------------------------------------------------------
# aggregate_videos: content_types filter clause construction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aggregate_no_content_types_defaults_to_video(mock_scene_client):
    client, async_client = mock_scene_client
    async_client.search = AsyncMock(return_value=_make_aggregate_response("vid-1"))

    await client.aggregate_videos("org-1")

    call_body = async_client.search.call_args[1]["body"]
    filters = call_body["query"]["bool"]["filter"]
    assert {"term": {"content_type": "video"}} in filters


@pytest.mark.asyncio
async def test_aggregate_single_content_type_uses_term(mock_scene_client):
    client, async_client = mock_scene_client
    async_client.search = AsyncMock(return_value=_make_aggregate_response("vid-1"))

    await client.aggregate_videos("org-1", content_types=["image"])

    call_body = async_client.search.call_args[1]["body"]
    filters = call_body["query"]["bool"]["filter"]
    assert {"term": {"content_type": "image"}} in filters
    assert {"term": {"content_type": "video"}} not in filters


@pytest.mark.asyncio
async def test_aggregate_multiple_content_types_uses_terms(mock_scene_client):
    client, async_client = mock_scene_client
    async_client.search = AsyncMock(return_value=_make_aggregate_response("vid-1"))

    await client.aggregate_videos("org-1", content_types=["video", "image"])

    call_body = async_client.search.call_args[1]["body"]
    filters = call_body["query"]["bool"]["filter"]
    assert {"terms": {"content_type": ["video", "image"]}} in filters


@pytest.mark.asyncio
async def test_aggregate_content_type_sub_aggregation_present(mock_scene_client):
    client, async_client = mock_scene_client
    async_client.search = AsyncMock(return_value=_make_aggregate_response("vid-1"))

    await client.aggregate_videos("org-1")

    call_body = async_client.search.call_args[1]["body"]
    composite_aggs = call_body["aggs"]["videos"]["aggs"]
    assert "content_type" in composite_aggs
    assert composite_aggs["content_type"] == {"terms": {"field": "content_type", "size": 1}}


# ---------------------------------------------------------------------------
# aggregate_videos: content_type in output
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aggregate_output_includes_content_type_video(mock_scene_client):
    client, async_client = mock_scene_client
    async_client.search = AsyncMock(return_value=_make_aggregate_response("vid-1", "video"))

    result = await client.aggregate_videos("org-1")

    assert result["videos"][0]["content_type"] == "video"


@pytest.mark.asyncio
async def test_aggregate_output_includes_content_type_image(mock_scene_client):
    client, async_client = mock_scene_client
    async_client.search = AsyncMock(return_value=_make_aggregate_response("img-1", "image"))

    result = await client.aggregate_videos("org-1", content_types=["image"])

    assert result["videos"][0]["content_type"] == "image"


@pytest.mark.asyncio
async def test_aggregate_output_defaults_content_type_when_missing(mock_scene_client):
    client, async_client = mock_scene_client
    response = _make_aggregate_response("vid-1")
    response["aggregations"]["videos"]["buckets"][0].pop("content_type")
    async_client.search = AsyncMock(return_value=response)

    result = await client.aggregate_videos("org-1")

    assert result["videos"][0]["content_type"] == "video"


# ---------------------------------------------------------------------------
# VideoSummary schema
# ---------------------------------------------------------------------------


def test_video_summary_content_type_field_optional():
    summary = VideoSummary(video_id="v1")
    assert summary.content_type is None


def test_video_summary_content_type_field_set():
    summary = VideoSummary(video_id="v1", content_type="image")
    assert summary.content_type == "image"


# ---------------------------------------------------------------------------
# Router: content_types query param parsing
# ---------------------------------------------------------------------------


def test_router_content_types_parsing_single():
    from app.modules.videos.router import list_videos
    # Verify the function signature accepts content_types param
    import inspect
    sig = inspect.signature(list_videos)
    assert "content_types" in sig.parameters


def test_content_types_comma_parsing():
    raw = "video,image"
    parsed = [ct.strip() for ct in raw.split(",") if ct.strip() in ("video", "image")]
    assert parsed == ["video", "image"]


def test_content_types_comma_parsing_single():
    raw = "image"
    parsed = [ct.strip() for ct in raw.split(",") if ct.strip() in ("video", "image")]
    assert parsed == ["image"]


def test_content_types_comma_parsing_invalid_filtered():
    raw = "video,invalid,image"
    parsed = [ct.strip() for ct in raw.split(",") if ct.strip() in ("video", "image")]
    assert parsed == ["video", "image"]


def test_content_types_comma_parsing_all_invalid():
    raw = "invalid,bad"
    parsed = [ct.strip() for ct in raw.split(",") if ct.strip() in ("video", "image")]
    assert parsed == []
