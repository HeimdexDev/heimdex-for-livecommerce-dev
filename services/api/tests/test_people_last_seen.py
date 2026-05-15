import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone


class TestLastSeenSceneTime:
    """Test suite for last_seen_scene_time population in GET /api/people response."""

    @pytest.fixture
    def mock_scene_client(self):
        """Mock OpenSearch scene client with ingest_time support."""
        with patch("app.modules.search.scene_client.get_settings") as mock_settings, \
             patch("app.modules.search.scene_client.get_opensearch_client"):

            settings = MagicMock()
            settings.opensearch_url = "http://localhost:9200"
            settings.opensearch_index_prefix = "test_scenes"
            settings.opensearch_bulk_refresh = "true"
            settings.ocr_search_enabled = True
            settings.ocr_bm25_boost = 0.6
            mock_settings.return_value = settings

            async_client = MagicMock()
            async_client.indices = MagicMock()
            async_client.close = AsyncMock()

            from app.modules.search.scene_client import SceneSearchClient
            client = SceneSearchClient()
            client.client = async_client

            yield client, async_client

    @pytest.mark.asyncio
    async def test_get_representative_scenes_includes_ingest_time(self, mock_scene_client):
        """Test that get_representative_scenes_for_people returns ingest_time."""
        client, async_client = mock_scene_client
        
        ingest_time_str = "2026-03-15T10:30:00Z"
        async_client.msearch = AsyncMock(return_value={
            "responses": [
                {
                    "hits": {
                        "hits": [
                            {
                                "_source": {
                                    "video_id": "vid_1",
                                    "scene_id": "vid_1_scene_0",
                                    "ingest_time": ingest_time_str,
                                }
                            }
                        ]
                    }
                }
            ]
        })

        result = await client.get_representative_scenes_for_people(
            "org_1", ["cluster_abc"]
        )

        assert "cluster_abc" in result
        assert result["cluster_abc"]["video_id"] == "vid_1"
        assert result["cluster_abc"]["scene_id"] == "vid_1_scene_0"
        assert result["cluster_abc"]["ingest_time"] == ingest_time_str

    @pytest.mark.asyncio
    async def test_get_representative_scenes_handles_missing_ingest_time(self, mock_scene_client):
        """Test that get_representative_scenes_for_people handles missing ingest_time gracefully."""
        client, async_client = mock_scene_client
        
        async_client.msearch = AsyncMock(return_value={
            "responses": [
                {
                    "hits": {
                        "hits": [
                            {
                                "_source": {
                                    "video_id": "vid_1",
                                    "scene_id": "vid_1_scene_0",
                                    # ingest_time missing
                                }
                            }
                        ]
                    }
                }
            ]
        })

        result = await client.get_representative_scenes_for_people(
            "org_1", ["cluster_abc"]
        )

        assert "cluster_abc" in result
        assert result["cluster_abc"]["ingest_time"] is None

    @pytest.mark.asyncio
    async def test_get_representative_scenes_requests_ingest_time_in_source(self, mock_scene_client):
        """Test that get_representative_scenes_for_people requests ingest_time in _source."""
        client, async_client = mock_scene_client
        
        async_client.msearch = AsyncMock(return_value={"responses": []})

        await client.get_representative_scenes_for_people("org_1", ["cluster_abc"])

        call_args = async_client.msearch.call_args
        body_parts = call_args.kwargs.get("body") or call_args[0][0]
        
        # body_parts is a list: [{"index": ...}, {"query": ..., "_source": ...}, ...]
        # Find the query part (odd indices)
        query_part = body_parts[1]
        assert "_source" in query_part
        assert "ingest_time" in query_part["_source"]
        assert "video_id" in query_part["_source"]
        assert "scene_id" in query_part["_source"]

    def test_person_response_has_last_seen_scene_time_field(self):
        """Test that PersonResponse schema includes last_seen_scene_time field."""
        from app.modules.people.schemas import PersonResponse

        person = PersonResponse(
            person_cluster_id="cluster_1",
            label="John Doe",
            face_count=5,
            last_seen_scene_time="2026-03-15T10:30:00Z",
            representative_video_id="vid_1",
            representative_scene_id="vid_1_scene_0",
            is_excluded=False,
        )

        assert person.last_seen_scene_time == "2026-03-15T10:30:00Z"

    def test_person_response_last_seen_scene_time_defaults_to_none(self):
        """Test that last_seen_scene_time defaults to None."""
        from app.modules.people.schemas import PersonResponse

        person = PersonResponse(
            person_cluster_id="cluster_1",
            label="John Doe",
            face_count=0,
        )

        assert person.last_seen_scene_time is None

    def test_person_response_last_seen_scene_time_can_be_null(self):
        """Test that last_seen_scene_time can be explicitly set to None."""
        from app.modules.people.schemas import PersonResponse

        person = PersonResponse(
            person_cluster_id="cluster_1",
            label="John Doe",
            face_count=0,
            last_seen_scene_time=None,
        )

        assert person.last_seen_scene_time is None

    def test_opensearch_facet_size_is_500(self):
        """Test that opensearch_facet_size is set to 500 in config."""
        from app.config import get_settings

        settings = get_settings()
        assert settings.opensearch_facet_size == 500
