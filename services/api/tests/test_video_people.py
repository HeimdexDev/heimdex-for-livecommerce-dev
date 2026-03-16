from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import (
    get_people_cluster_label_repository,
    get_people_exclude_preference_repository,
    get_scene_opensearch_client,
)
from app.modules.auth import get_current_user
from app.modules.tenancy import OrgContext, get_current_org
from app.modules.videos.router import router as videos_router


class TestGetPeopleByVideo:

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
    async def test_get_people_by_video_returns_clusters(self, mock_scene_client):
        client, async_client = mock_scene_client
        async_client.search = AsyncMock(return_value={
            "aggregations": {
                "by_person": {
                    "buckets": [
                        {"key": "person_1", "doc_count": 12},
                        {"key": "person_2", "doc_count": 7},
                        {"key": "person_3", "doc_count": 3},
                    ],
                },
            },
        })

        result = await client.get_people_by_video("org_1", "vid_1")

        assert result == [
            {"person_cluster_id": "person_1", "face_count": 12},
            {"person_cluster_id": "person_2", "face_count": 7},
            {"person_cluster_id": "person_3", "face_count": 3},
        ]

    @pytest.mark.asyncio
    async def test_get_people_by_video_empty_video(self, mock_scene_client):
        client, async_client = mock_scene_client
        async_client.search = AsyncMock(return_value={
            "aggregations": {"by_person": {"buckets": []}},
        })

        result = await client.get_people_by_video("org_1", "vid_empty")

        assert result == []

    @pytest.mark.asyncio
    async def test_get_people_by_video_query_structure(self, mock_scene_client):
        client, async_client = mock_scene_client
        async_client.search = AsyncMock(return_value={
            "aggregations": {"by_person": {"buckets": []}},
        })

        await client.get_people_by_video("org_xyz", "vid_abc")

        call_args = async_client.search.call_args
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        filters = body["query"]["bool"]["filter"]
        assert {"term": {"org_id": "org_xyz"}} in filters
        assert {"term": {"video_id": "vid_abc"}} in filters
        assert {"term": {"content_type": "video"}} in filters
        assert {"exists": {"field": "people_cluster_ids"}} in filters


class TestVideoPeopleEndpoint:

    def _build_app(
        self,
        *,
        org_id,
        user_id,
        scene_opensearch,
        people_repo,
        exclude_repo,
    ) -> FastAPI:
        app = FastAPI()
        app.include_router(videos_router, prefix="/api")

        async def _mock_get_current_org() -> OrgContext:
            return OrgContext(org_id=org_id, org_slug="testorg")

        async def _mock_get_current_user() -> SimpleNamespace:
            return SimpleNamespace(id=user_id)

        async def _mock_get_scene_client() -> MagicMock:
            return scene_opensearch

        async def _mock_get_people_repo() -> MagicMock:
            return people_repo

        async def _mock_get_exclude_repo() -> MagicMock:
            return exclude_repo

        app.dependency_overrides[get_current_org] = _mock_get_current_org
        app.dependency_overrides[get_current_user] = _mock_get_current_user
        app.dependency_overrides[get_scene_opensearch_client] = _mock_get_scene_client
        app.dependency_overrides[get_people_cluster_label_repository] = _mock_get_people_repo
        app.dependency_overrides[get_people_exclude_preference_repository] = _mock_get_exclude_repo
        return app

    def test_video_people_returns_correct_shape(self):
        org_id = uuid4()
        user_id = uuid4()

        scene_opensearch = MagicMock()
        scene_opensearch.get_people_by_video = AsyncMock(return_value=[
            {"person_cluster_id": "person_1", "face_count": 10},
            {"person_cluster_id": "person_2", "face_count": 4},
        ])
        scene_opensearch.get_representative_scenes_for_people = AsyncMock(return_value={
            "person_1": {
                "video_id": "vid_1",
                "scene_id": "vid_1_scene_10",
                "ingest_time": "2026-03-16T10:00:00Z",
            },
            "person_2": {
                "video_id": "vid_1",
                "scene_id": "vid_1_scene_04",
                "ingest_time": "2026-03-16T09:00:00Z",
            },
        })

        people_repo = MagicMock()
        people_repo.list_by_org = AsyncMock(return_value=[
            SimpleNamespace(person_cluster_id="person_1", label="Alice"),
            SimpleNamespace(person_cluster_id="person_2", label="Bob"),
        ])

        exclude_repo = MagicMock()
        exclude_repo.list_by_user = AsyncMock(return_value=["person_2"])

        app = self._build_app(
            org_id=org_id,
            user_id=user_id,
            scene_opensearch=scene_opensearch,
            people_repo=people_repo,
            exclude_repo=exclude_repo,
        )

        with patch("app.modules.videos.router.get_settings", return_value=SimpleNamespace(people_enabled=True)):
            with TestClient(app) as client:
                response = client.get("/api/videos/vid_1/people")

        assert response.status_code == 200
        payload = response.json()
        assert payload["video_id"] == "vid_1"
        assert payload["total"] == 2
        assert payload["people"][0]["person_cluster_id"] == "person_1"
        assert payload["people"][0]["label"] == "Alice"
        assert payload["people"][0]["face_count"] == 10
        assert payload["people"][1]["person_cluster_id"] == "person_2"
        assert payload["people"][1]["label"] == "Bob"
        assert payload["people"][1]["face_count"] == 4

    def test_video_people_empty_returns_zero(self):
        org_id = uuid4()
        user_id = uuid4()

        scene_opensearch = MagicMock()
        scene_opensearch.get_people_by_video = AsyncMock(return_value=[])
        scene_opensearch.get_representative_scenes_for_people = AsyncMock(return_value={})

        people_repo = MagicMock()
        people_repo.list_by_org = AsyncMock(return_value=[])

        exclude_repo = MagicMock()
        exclude_repo.list_by_user = AsyncMock(return_value=[])

        app = self._build_app(
            org_id=org_id,
            user_id=user_id,
            scene_opensearch=scene_opensearch,
            people_repo=people_repo,
            exclude_repo=exclude_repo,
        )

        with patch("app.modules.videos.router.get_settings", return_value=SimpleNamespace(people_enabled=True)):
            with TestClient(app) as client:
                response = client.get("/api/videos/vid_empty/people")

        assert response.status_code == 200
        assert response.json() == {
            "video_id": "vid_empty",
            "people": [],
            "total": 0,
        }

    def test_video_people_disabled_returns_404(self):
        org_id = uuid4()
        user_id = uuid4()

        scene_opensearch = MagicMock()
        scene_opensearch.get_people_by_video = AsyncMock(return_value=[])
        scene_opensearch.get_representative_scenes_for_people = AsyncMock(return_value={})

        people_repo = MagicMock()
        people_repo.list_by_org = AsyncMock(return_value=[])

        exclude_repo = MagicMock()
        exclude_repo.list_by_user = AsyncMock(return_value=[])

        app = self._build_app(
            org_id=org_id,
            user_id=user_id,
            scene_opensearch=scene_opensearch,
            people_repo=people_repo,
            exclude_repo=exclude_repo,
        )

        with patch("app.modules.videos.router.get_settings", return_value=SimpleNamespace(people_enabled=False)):
            with TestClient(app) as client:
                response = client.get("/api/videos/vid_1/people")

        assert response.status_code == 404
        assert response.json()["detail"] == "People feature is not enabled"

    def test_video_people_response_schema(self):
        from app.modules.people.schemas import PersonResponse
        from app.modules.videos.schemas import VideoPeopleResponse

        response = VideoPeopleResponse(
            video_id="vid_1",
            people=[
                PersonResponse(
                    person_cluster_id="person_1",
                    label="Alice",
                    face_count=3,
                    is_excluded=False,
                )
            ],
            total=1,
        )

        assert response.video_id == "vid_1"
        assert response.total == 1
        assert response.people[0].person_cluster_id == "person_1"
        assert response.people[0].label == "Alice"
