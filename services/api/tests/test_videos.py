"""
Unit tests for the video visibility module.

Tests cover:
1. SceneSearchClient: aggregate_videos, get_video_scenes, get_video_stats
2. VideoService: list_videos, get_video_scenes, get_stats
3. Schema validation
4. Cursor encoding/decoding
5. Org isolation (every query includes org_id filter)
6. Empty index handling

Run with: pytest tests/test_videos.py -v
"""
import base64
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


# ======================================================================
# SceneSearchClient — aggregate_videos
# ======================================================================

class TestSceneClientAggregateVideos:
    """Tests for SceneSearchClient.aggregate_videos."""

    @pytest.fixture
    def mock_scene_client(self):
        with patch("app.modules.search.scene_client.get_settings") as mock_settings, \
             patch("app.modules.search.scene_client.get_opensearch_client") as mock_get_client:

            settings = MagicMock()
            settings.opensearch_url = "http://localhost:9200"
            settings.opensearch_index_prefix = "test"
            mock_settings.return_value = settings

            async_client = MagicMock()
            async_client.indices = MagicMock()
            async_client.close = AsyncMock()
            mock_get_client.return_value = async_client

            from app.modules.search.scene_client import SceneSearchClient
            client = SceneSearchClient()
            client.client = async_client

            yield client, async_client

    def _make_agg_response(self, buckets, total=1, after_key=None):
        """Build a mock OpenSearch aggregation response."""
        result = {
            "aggregations": {
                "videos": {
                    "buckets": buckets,
                },
                "total_videos": {"value": total},
                "facet_libraries": {"buckets": [{"key": "lib-1", "doc_count": 5}]},
                "facet_source_types": {"buckets": [{"key": "gdrive", "doc_count": 5}]},
            }
        }
        if after_key:
            result["aggregations"]["videos"]["after_key"] = after_key
        return result

    def _make_video_bucket(
        self,
        video_id="vid-1",
        video_title="Sample Video",
        scene_count=5,
        lib_id="lib-1",
        source_type="gdrive",
        ingest_time="2026-02-10T05:00:00Z",
    ):
        return {
            "key": {"video_id": video_id},
            "doc_count": scene_count,
            "scene_count": {"value": scene_count},
            "min_start_ms": {"value": 0},
            "max_end_ms": {"value": 60000},
            "earliest_ingest": {"value": 1000, "value_as_string": ingest_time},
            "latest_ingest": {"value": 2000, "value_as_string": ingest_time},
            "library_id": {"buckets": [{"key": lib_id, "doc_count": scene_count}]},
            "video_title": {"buckets": [{"key": video_title, "doc_count": scene_count}]},
            "source_type": {"buckets": [{"key": source_type, "doc_count": scene_count}]},
            "required_drive_nickname": {"buckets": []},
            "source_path": {"buckets": []},
            "keyword_tags": {"buckets": [{"key": "review", "doc_count": 3}]},
            "product_tags": {"buckets": [{"key": "skincare", "doc_count": 2}]},
            "people_count": {"value": 1},
            "min_keyframe_ms": {"value": 500},
            "earliest_capture": {"value": None, "value_as_string": None},
        }

    @pytest.mark.asyncio
    async def test_aggregate_videos_returns_video_list(self, mock_scene_client):
        client, mock_async = mock_scene_client
        bucket = self._make_video_bucket()
        mock_async.search = AsyncMock(return_value=self._make_agg_response([bucket]))

        result = await client.aggregate_videos("org-1")

        assert len(result["videos"]) == 1
        video = result["videos"][0]
        assert video["video_id"] == "vid-1"
        assert video["video_title"] == "Sample Video"
        assert video["scene_count"] == 5
        assert video["library_id"] == "lib-1"
        assert video["source_type"] == "gdrive"
        assert video["keyword_tags"] == ["review"]
        assert video["product_tags"] == ["skincare"]
        assert video["people_count"] == 1

    @pytest.mark.asyncio
    async def test_aggregate_videos_includes_org_filter(self, mock_scene_client):
        client, mock_async = mock_scene_client
        mock_async.search = AsyncMock(return_value=self._make_agg_response([]))

        await client.aggregate_videos("my-org-123")

        call_body = mock_async.search.call_args.kwargs["body"]
        filters = call_body["query"]["bool"]["filter"]
        org_terms = [f for f in filters if "term" in f and "org_id" in f["term"]]
        assert len(org_terms) == 1
        assert org_terms[0]["term"]["org_id"] == "my-org-123"

    @pytest.mark.asyncio
    async def test_aggregate_videos_applies_library_filter(self, mock_scene_client):
        client, mock_async = mock_scene_client
        mock_async.search = AsyncMock(return_value=self._make_agg_response([]))

        await client.aggregate_videos("org-1", library_id="lib-abc")

        call_body = mock_async.search.call_args.kwargs["body"]
        filters = call_body["query"]["bool"]["filter"]
        lib_terms = [f for f in filters if "term" in f and "library_id" in f.get("term", {})]
        assert len(lib_terms) == 1
        assert lib_terms[0]["term"]["library_id"] == "lib-abc"

    @pytest.mark.asyncio
    async def test_aggregate_videos_applies_source_type_filter(self, mock_scene_client):
        client, mock_async = mock_scene_client
        mock_async.search = AsyncMock(return_value=self._make_agg_response([]))

        await client.aggregate_videos("org-1", source_type="removable_disk")

        call_body = mock_async.search.call_args.kwargs["body"]
        filters = call_body["query"]["bool"]["filter"]
        src_terms = [f for f in filters if "term" in f and "source_type" in f.get("term", {})]
        assert len(src_terms) == 1
        assert src_terms[0]["term"]["source_type"] == "removable_disk"

    @pytest.mark.asyncio
    async def test_aggregate_videos_empty_index(self, mock_scene_client):
        client, mock_async = mock_scene_client
        mock_async.search = AsyncMock(return_value=self._make_agg_response([], total=0))

        result = await client.aggregate_videos("org-1")

        assert result["videos"] == []
        assert result["total"] == 0
        assert result["next_cursor"] is None

    @pytest.mark.asyncio
    async def test_aggregate_videos_pagination_cursor(self, mock_scene_client):
        client, mock_async = mock_scene_client
        after = {"video_id": "last-vid"}
        mock_async.search = AsyncMock(
            return_value=self._make_agg_response(
                [self._make_video_bucket()],
                after_key=after,
            )
        )

        result = await client.aggregate_videos("org-1")

        assert result["next_cursor"] == after

    @pytest.mark.asyncio
    async def test_aggregate_videos_passes_after_key(self, mock_scene_client):
        client, mock_async = mock_scene_client
        mock_async.search = AsyncMock(return_value=self._make_agg_response([]))

        after_key = {"video_id": "cursor-vid"}
        await client.aggregate_videos("org-1", after_key=after_key)

        call_body = mock_async.search.call_args.kwargs["body"]
        composite = call_body["aggs"]["videos"]["composite"]
        assert composite["after"] == after_key

    @pytest.mark.asyncio
    async def test_aggregate_videos_sort_latest(self, mock_scene_client):
        client, mock_async = mock_scene_client
        b1 = self._make_video_bucket("vid-old", ingest_time="2026-01-01T00:00:00Z")
        b2 = self._make_video_bucket("vid-new", ingest_time="2026-02-10T00:00:00Z")
        mock_async.search = AsyncMock(
            return_value=self._make_agg_response([b1, b2], total=2)
        )

        result = await client.aggregate_videos("org-1", sort="latest")

        assert result["videos"][0]["video_id"] == "vid-new"
        assert result["videos"][1]["video_id"] == "vid-old"

    @pytest.mark.asyncio
    async def test_aggregate_videos_sort_oldest(self, mock_scene_client):
        client, mock_async = mock_scene_client
        b1 = self._make_video_bucket("vid-old", ingest_time="2026-01-01T00:00:00Z")
        b2 = self._make_video_bucket("vid-new", ingest_time="2026-02-10T00:00:00Z")
        mock_async.search = AsyncMock(
            return_value=self._make_agg_response([b1, b2], total=2)
        )

        result = await client.aggregate_videos("org-1", sort="oldest")

        assert result["videos"][0]["video_id"] == "vid-old"
        assert result["videos"][1]["video_id"] == "vid-new"


# ======================================================================
# SceneSearchClient — get_video_scenes
# ======================================================================

class TestSceneClientGetVideoScenes:
    @pytest.fixture
    def mock_scene_client(self):
        with patch("app.modules.search.scene_client.get_settings") as mock_settings, \
             patch("app.modules.search.scene_client.get_opensearch_client") as mock_get_client:

            settings = MagicMock()
            settings.opensearch_url = "http://localhost:9200"
            settings.opensearch_index_prefix = "test"
            mock_settings.return_value = settings

            async_client = MagicMock()
            async_client.indices = MagicMock()
            async_client.close = AsyncMock()
            mock_get_client.return_value = async_client

            from app.modules.search.scene_client import SceneSearchClient
            client = SceneSearchClient()
            client.client = async_client

            yield client, async_client

    @pytest.mark.asyncio
    async def test_get_video_scenes_returns_sorted_scenes(self, mock_scene_client):
        client, mock_async = mock_scene_client
        mock_async.search = AsyncMock(return_value={
            "hits": {
                "total": {"value": 2, "relation": "eq"},
                "hits": [
                    {
                        "_id": "org:scene_0",
                        "_source": {
                            "scene_id": "vid_scene_0",
                            "start_ms": 0,
                            "end_ms": 5000,
                            "transcript_raw": "First scene",
                            "transcript_char_count": 11,
                            "keyword_tags": ["intro"],
                            "product_tags": [],
                            "product_entities": [],
                            "speech_segment_count": 2,
                            "people_cluster_ids": [],
                            "ingest_time": "2026-02-10T05:00:00Z",
                        },
                    },
                    {
                        "_id": "org:scene_1",
                        "_source": {
                            "scene_id": "vid_scene_1",
                            "start_ms": 5000,
                            "end_ms": 10000,
                            "transcript_raw": "Second scene",
                            "transcript_char_count": 12,
                            "keyword_tags": [],
                            "product_tags": ["skincare"],
                            "product_entities": [],
                            "speech_segment_count": 1,
                            "people_cluster_ids": ["person-a"],
                            "ingest_time": "2026-02-10T05:00:00Z",
                        },
                    },
                ],
            },
        })

        result = await client.get_video_scenes("org-1", "vid-1")

        assert len(result["scenes"]) == 2
        assert result["total"] == 2
        assert result["scenes"][0]["scene_id"] == "vid_scene_0"
        assert result["scenes"][1]["scene_id"] == "vid_scene_1"

    @pytest.mark.asyncio
    async def test_get_video_scenes_includes_org_and_video_filters(self, mock_scene_client):
        client, mock_async = mock_scene_client
        mock_async.search = AsyncMock(return_value={
            "hits": {"total": {"value": 0}, "hits": []},
        })

        await client.get_video_scenes("org-abc", "vid-xyz")

        call_body = mock_async.search.call_args.kwargs["body"]
        filters = call_body["query"]["bool"]["filter"]
        org_terms = [f for f in filters if "term" in f and "org_id" in f["term"]]
        vid_terms = [f for f in filters if "term" in f and "video_id" in f["term"]]
        assert len(org_terms) == 1
        assert org_terms[0]["term"]["org_id"] == "org-abc"
        assert len(vid_terms) == 1
        assert vid_terms[0]["term"]["video_id"] == "vid-xyz"

    @pytest.mark.asyncio
    async def test_get_video_scenes_empty_result(self, mock_scene_client):
        client, mock_async = mock_scene_client
        mock_async.search = AsyncMock(return_value={
            "hits": {"total": {"value": 0}, "hits": []},
        })

        result = await client.get_video_scenes("org-1", "nonexistent-vid")

        assert result["scenes"] == []
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_get_video_scenes_pagination(self, mock_scene_client):
        client, mock_async = mock_scene_client
        mock_async.search = AsyncMock(return_value={
            "hits": {"total": {"value": 0}, "hits": []},
        })

        await client.get_video_scenes("org-1", "vid-1", page_size=10, offset=20)

        call_body = mock_async.search.call_args.kwargs["body"]
        assert call_body["size"] == 10
        assert call_body["from"] == 20


# ======================================================================
# SceneSearchClient — get_video_stats
# ======================================================================

class TestSceneClientGetVideoStats:
    @pytest.fixture
    def mock_scene_client(self):
        with patch("app.modules.search.scene_client.get_settings") as mock_settings, \
             patch("app.modules.search.scene_client.get_opensearch_client") as mock_get_client:

            settings = MagicMock()
            settings.opensearch_url = "http://localhost:9200"
            settings.opensearch_index_prefix = "test"
            mock_settings.return_value = settings

            async_client = MagicMock()
            async_client.indices = MagicMock()
            async_client.close = AsyncMock()
            mock_get_client.return_value = async_client

            from app.modules.search.scene_client import SceneSearchClient
            client = SceneSearchClient()
            client.client = async_client

            yield client, async_client

    @pytest.mark.asyncio
    async def test_get_video_stats_returns_all_fields(self, mock_scene_client):
        client, mock_async = mock_scene_client
        mock_async.search = AsyncMock(return_value={
            "hits": {"total": {"value": 100}},
            "aggregations": {
                "total_videos": {"value": 15},
                "total_libraries": {"value": 3},
                "source_breakdown": {
                    "buckets": [
                        {"key": "gdrive", "doc_count": 80},
                        {"key": "removable_disk", "doc_count": 20},
                    ]
                },
                "latest_ingest": {"value": 1000, "value_as_string": "2026-02-10T05:00:00Z"},
                "latest_capture": {"value": 900, "value_as_string": "2026-02-09T12:00:00Z"},
                "scenes_last_24h": {"doc_count": 25},
                "scenes_last_7d": {"doc_count": 75},
            },
        })

        result = await client.get_video_stats("org-1")

        assert result["total_videos"] == 15
        assert result["total_scenes"] == 100
        assert result["total_libraries"] == 3
        assert result["source_breakdown"] == {"gdrive": 80, "removable_disk": 20}
        assert result["latest_ingest_time"] == "2026-02-10T05:00:00Z"
        assert result["scenes_last_24h"] == 25
        assert result["scenes_last_7d"] == 75

    @pytest.mark.asyncio
    async def test_get_video_stats_includes_org_filter(self, mock_scene_client):
        client, mock_async = mock_scene_client
        mock_async.search = AsyncMock(return_value={
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
        })

        await client.get_video_stats("my-org")

        call_body = mock_async.search.call_args.kwargs["body"]
        filters = call_body["query"]["bool"]["filter"]
        org_terms = [f for f in filters if "term" in f and "org_id" in f["term"]]
        assert len(org_terms) == 1
        assert org_terms[0]["term"]["org_id"] == "my-org"

    @pytest.mark.asyncio
    async def test_get_video_stats_empty_index(self, mock_scene_client):
        client, mock_async = mock_scene_client
        mock_async.search = AsyncMock(return_value={
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
        })

        result = await client.get_video_stats("org-1")

        assert result["total_videos"] == 0
        assert result["total_scenes"] == 0
        assert result["source_breakdown"] == {}
        assert result["latest_ingest_time"] is None
        assert result["scenes_last_24h"] == 0


# ======================================================================
# VideoService
# ======================================================================

class TestVideoService:
    @pytest.fixture
    def mock_scene_client(self):
        client = MagicMock()
        client.aggregate_videos = AsyncMock()
        client.get_video_scenes = AsyncMock()
        client.get_video_stats = AsyncMock()
        return client

    @pytest.fixture
    def service(self, mock_db_session, mock_scene_client):
        from app.modules.videos.service import VideoService
        return VideoService(mock_db_session, mock_scene_client)

    def _mock_library_repo(self, mock_db_session, libraries=None):
        """Set up mock library repo via db session mock."""
        if libraries is None:
            lib = MagicMock()
            lib.id = uuid4()
            lib.name = "Test Library"
            libraries = [lib]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = libraries
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        return {str(lib.id): lib.name for lib in libraries}

    @pytest.mark.asyncio
    async def test_list_videos_happy_path(self, service, mock_db_session, mock_scene_client):
        lib_uuid = uuid4()
        lib_id = str(lib_uuid)
        mock_lib = MagicMock()
        mock_lib.id = lib_uuid
        mock_lib.name = "My Library"
        self._mock_library_repo(mock_db_session, [mock_lib])

        mock_scene_client.aggregate_videos.return_value = {
            "videos": [{
                "video_id": "vid-1",
                "video_title": "Sample Video",
                "library_id": lib_id,
                "source_type": "gdrive",
                "scene_count": 10,
                "first_scene_start_ms": 0,
                "last_scene_end_ms": 60000,
                "earliest_ingest_time": "2026-02-10T00:00:00Z",
                "latest_ingest_time": "2026-02-10T00:00:00Z",
                "keyword_tags": ["review"],
                "product_tags": ["skincare"],
                "people_count": 2,
                "required_drive_nickname": None,
            }],
            "total": 1,
            "next_cursor": None,
            "facets": {
                "libraries": [{"key": lib_id, "doc_count": 10}],
                "source_types": [{"key": "gdrive", "doc_count": 10}],
            },
        }

        org_id = uuid4()
        result = await service.list_videos(org_id)

        assert len(result.videos) == 1
        assert result.videos[0].video_id == "vid-1"
        assert result.videos[0].video_title == "Sample Video"
        assert result.videos[0].library_name == "My Library"
        assert result.total == 1
        assert result.next_cursor is None

    @pytest.mark.asyncio
    async def test_list_videos_cursor_encoding(self, service, mock_db_session, mock_scene_client):
        self._mock_library_repo(mock_db_session)

        after_key = {"video_id": "last-vid"}
        mock_scene_client.aggregate_videos.return_value = {
            "videos": [],
            "total": 0,
            "next_cursor": after_key,
            "facets": {"libraries": [], "source_types": []},
        }

        org_id = uuid4()
        result = await service.list_videos(org_id)

        assert result.next_cursor is not None
        decoded = json.loads(base64.urlsafe_b64decode(result.next_cursor))
        assert decoded == after_key

    @pytest.mark.asyncio
    async def test_list_videos_cursor_decoding(self, service, mock_db_session, mock_scene_client):
        self._mock_library_repo(mock_db_session)

        mock_scene_client.aggregate_videos.return_value = {
            "videos": [],
            "total": 0,
            "next_cursor": None,
            "facets": {"libraries": [], "source_types": []},
        }

        cursor_data = {"video_id": "cursor-vid"}
        cursor = base64.urlsafe_b64encode(json.dumps(cursor_data).encode()).decode()

        org_id = uuid4()
        await service.list_videos(org_id, after_cursor=cursor)

        call_kwargs = mock_scene_client.aggregate_videos.call_args.kwargs
        assert call_kwargs["after_key"] == cursor_data

    @pytest.mark.asyncio
    async def test_list_videos_invalid_cursor_ignored(self, service, mock_db_session, mock_scene_client):
        self._mock_library_repo(mock_db_session)

        mock_scene_client.aggregate_videos.return_value = {
            "videos": [],
            "total": 0,
            "next_cursor": None,
            "facets": {"libraries": [], "source_types": []},
        }

        org_id = uuid4()
        # Should not raise
        await service.list_videos(org_id, after_cursor="not-valid-base64!!!")

        call_kwargs = mock_scene_client.aggregate_videos.call_args.kwargs
        assert call_kwargs["after_key"] is None

    @pytest.mark.asyncio
    async def test_get_video_scenes_happy_path(self, service, mock_db_session, mock_scene_client):
        mock_scene_client.get_video_scenes.return_value = {
            "scenes": [{
                "scene_id": "vid_scene_0",
                "start_ms": 0,
                "end_ms": 5000,
                "transcript_raw": "Hello",
                "transcript_char_count": 5,
                "keyword_tags": [],
                "product_tags": [],
                "product_entities": [],
                "speech_segment_count": 1,
                "people_cluster_ids": [],
                "ingest_time": "2026-02-10T00:00:00Z",
            }],
            "total": 1,
        }

        org_id = uuid4()
        result = await service.get_video_scenes(org_id, "vid-1")

        assert result.video_id == "vid-1"
        assert len(result.scenes) == 1
        assert result.scenes[0].scene_id == "vid_scene_0"
        assert result.total == 1

    @pytest.mark.asyncio
    async def test_get_stats_happy_path(self, service, mock_db_session, mock_scene_client):
        mock_scene_client.get_video_stats.return_value = {
            "total_videos": 15,
            "total_scenes": 200,
            "total_libraries": 3,
            "source_breakdown": {"gdrive": 150, "removable_disk": 50},
            "latest_ingest_time": "2026-02-10T00:00:00Z",
            "scenes_last_24h": 30,
            "scenes_last_7d": 150,
        }

        org_id = uuid4()
        result = await service.get_stats(org_id)

        assert result.total_videos == 15
        assert result.total_scenes == 200
        assert result.total_libraries == 3
        assert result.scenes_last_24h == 30


# ======================================================================
# Schema tests
# ======================================================================

class TestVideoSchemas:
    def test_video_summary_defaults(self):
        from app.modules.videos.schemas import VideoSummary

        v = VideoSummary(video_id="vid-1")
        assert v.video_id == "vid-1"
        assert v.video_title is None
        assert v.scene_count == 0
        assert v.keyword_tags == []
        assert v.product_tags == []
        assert v.people_count == 0
        assert v.source_type is None
        assert v.library_name is None

    def test_video_summary_full(self):
        from app.modules.videos.schemas import VideoSummary

        v = VideoSummary(
            video_id="vid-1",
            video_title="Sample Video",
            library_id="lib-1",
            library_name="My Lib",
            source_type="gdrive",
            scene_count=42,
            first_scene_start_ms=0,
            last_scene_end_ms=60000,
            earliest_ingest_time="2026-02-10T00:00:00Z",
            latest_ingest_time="2026-02-10T00:00:00Z",
            keyword_tags=["review", "unboxing"],
            product_tags=["skincare"],
            people_count=3,
            required_drive_nickname=None,
        )
        assert v.scene_count == 42
        assert v.video_title == "Sample Video"
        assert v.keyword_tags == ["review", "unboxing"]

    def test_video_stats_defaults(self):
        from app.modules.videos.schemas import VideoStats

        s = VideoStats()
        assert s.total_videos == 0
        assert s.total_scenes == 0
        assert s.source_breakdown == {}
        assert s.latest_ingest_time is None
        assert s.scenes_last_24h == 0

    def test_video_scene_defaults(self):
        from app.modules.videos.schemas import VideoScene

        sc = VideoScene(scene_id="s1", start_ms=0, end_ms=1000)
        assert sc.transcript_raw == ""
        assert sc.keyword_tags == []
        assert sc.speech_segment_count == 0

    def test_video_list_response_structure(self):
        from app.modules.videos.schemas import (
            VideoListResponse,
            VideoSummary,
            VideoFacets,
        )

        resp = VideoListResponse(
            videos=[VideoSummary(video_id="v1")],
            total=1,
            next_cursor=None,
            facets=VideoFacets(),
        )
        assert len(resp.videos) == 1
        assert resp.total == 1
        assert resp.facets.libraries == []
