import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestSearchPeopleByVideoTitle:

    @pytest.fixture
    def mock_scene_client(self):
        with patch("app.modules.search.scene_client.get_settings") as mock_settings, \
             patch("app.modules.search.scene_client.get_opensearch_client"):

            settings = MagicMock()
            settings.opensearch_url = "http://localhost:9200"
            settings.opensearch_index_prefix = "test_scenes"
            settings.opensearch_bulk_refresh = "true"
            settings.ocr_search_enabled = True
            settings.ocr_bm25_boost = 0.6
            settings.opensearch_facet_size = 500
            mock_settings.return_value = settings

            async_client = MagicMock()
            async_client.indices = MagicMock()
            async_client.close = AsyncMock()

            from app.modules.search.scene_client import SceneSearchClient
            client = SceneSearchClient()
            client.client = async_client

            yield client, async_client

    @pytest.mark.asyncio
    async def test_returns_matching_clusters_with_titles(self, mock_scene_client):
        client, async_client = mock_scene_client
        async_client.search = AsyncMock(return_value={
            "aggregations": {
                "matching_people": {
                    "buckets": [
                        {
                            "key": "person_abc",
                            "doc_count": 10,
                            "video_titles": {
                                "buckets": [
                                    {"key": "써모스 라이브", "doc_count": 7},
                                    {"key": "써모스 특가", "doc_count": 3},
                                ]
                            },
                        },
                        {
                            "key": "person_def",
                            "doc_count": 5,
                            "video_titles": {
                                "buckets": [
                                    {"key": "써모스 라이브", "doc_count": 5},
                                ]
                            },
                        },
                    ]
                }
            }
        })

        result = await client.search_people_by_video_title("org_1", "써모스")

        assert result == {
            "person_abc": ["써모스 라이브", "써모스 특가"],
            "person_def": ["써모스 라이브"],
        }

    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_no_matches(self, mock_scene_client):
        client, async_client = mock_scene_client
        async_client.search = AsyncMock(return_value={
            "aggregations": {
                "matching_people": {"buckets": []}
            }
        })

        result = await client.search_people_by_video_title("org_1", "존재하지않는영상")

        assert result == {}

    @pytest.mark.asyncio
    async def test_query_uses_nori_and_wildcard(self, mock_scene_client):
        client, async_client = mock_scene_client
        async_client.search = AsyncMock(return_value={
            "aggregations": {"matching_people": {"buckets": []}}
        })

        await client.search_people_by_video_title("org_1", "테스트")

        call_args = async_client.search.call_args
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        bool_clause = body["query"]["bool"]
        should = bool_clause["should"]
        assert bool_clause["minimum_should_match"] == 1
        assert any("video_title.nori" in str(c) for c in should)
        assert any("wildcard" in str(c) for c in should)

    @pytest.mark.asyncio
    async def test_query_filters_by_org_and_content_type(self, mock_scene_client):
        client, async_client = mock_scene_client
        async_client.search = AsyncMock(return_value={
            "aggregations": {"matching_people": {"buckets": []}}
        })

        await client.search_people_by_video_title("org_xyz", "검색어")

        call_args = async_client.search.call_args
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        filters = body["query"]["bool"]["filter"]
        assert {"term": {"org_id": "org_xyz"}} in filters
        assert {"term": {"content_type": "video"}} in filters
        assert {"exists": {"field": "people_cluster_ids"}} in filters

    @pytest.mark.asyncio
    async def test_cluster_with_empty_video_titles(self, mock_scene_client):
        client, async_client = mock_scene_client
        async_client.search = AsyncMock(return_value={
            "aggregations": {
                "matching_people": {
                    "buckets": [
                        {
                            "key": "person_no_title",
                            "doc_count": 2,
                            "video_titles": {"buckets": []},
                        },
                    ]
                }
            }
        })

        result = await client.search_people_by_video_title("org_1", "쿼리")

        assert result == {"person_no_title": []}


class TestSearchByLabel:

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_returns_matching_cluster_ids(self, mock_session):
        from app.modules.people.repository import PeopleClusterLabelRepository

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [
            "cluster_a", "cluster_b"
        ]
        mock_session.execute = AsyncMock(return_value=mock_result)

        repo = PeopleClusterLabelRepository(mock_session)
        result = await repo.search_by_label(
            MagicMock(), "홍길동"
        )

        assert result == ["cluster_a", "cluster_b"]

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_matches(self, mock_session):
        from app.modules.people.repository import PeopleClusterLabelRepository

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        repo = PeopleClusterLabelRepository(mock_session)
        result = await repo.search_by_label(
            MagicMock(), "없는이름"
        )

        assert result == []


class TestListPeopleSearchParam:

    def test_person_response_matched_video_titles_defaults_to_none(self):
        from app.modules.people.schemas import PersonResponse

        person = PersonResponse(
            person_cluster_id="cluster_1",
            face_count=5,
        )
        assert person.matched_video_titles is None

    def test_person_response_matched_video_titles_can_be_set(self):
        from app.modules.people.schemas import PersonResponse

        person = PersonResponse(
            person_cluster_id="cluster_1",
            face_count=5,
            matched_video_titles=["영상A", "영상B"],
        )
        assert person.matched_video_titles == ["영상A", "영상B"]

    def test_person_response_matched_video_titles_empty_list(self):
        from app.modules.people.schemas import PersonResponse

        person = PersonResponse(
            person_cluster_id="cluster_1",
            face_count=0,
            matched_video_titles=[],
        )
        assert person.matched_video_titles == []

    def test_person_response_serialization_includes_matched_titles(self):
        from app.modules.people.schemas import PersonResponse

        person = PersonResponse(
            person_cluster_id="cluster_1",
            face_count=5,
            matched_video_titles=["라이브 방송"],
        )
        data = person.model_dump()
        assert data["matched_video_titles"] == ["라이브 방송"]

    def test_person_response_serialization_omits_none_titles(self):
        from app.modules.people.schemas import PersonResponse

        person = PersonResponse(
            person_cluster_id="cluster_1",
            face_count=5,
        )
        data = person.model_dump()
        assert data["matched_video_titles"] is None
