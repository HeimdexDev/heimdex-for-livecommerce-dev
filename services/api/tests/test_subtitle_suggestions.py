"""Tests for subtitle suggestion endpoint."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_scene_opensearch_client, get_shorts_render_service
from app.modules.auth import get_current_user
from app.modules.shorts_render.router import router as shorts_render_router
from app.modules.tenancy import OrgContext, get_current_org


ORG_ID = uuid4()
USER_ID = uuid4()


def _build_app(mock_scene_client: MagicMock) -> FastAPI:
    app = FastAPI()
    app.include_router(shorts_render_router, prefix="/api")

    async def _mock_org() -> OrgContext:
        return OrgContext(org_id=ORG_ID, org_slug="testorg")

    async def _mock_user() -> SimpleNamespace:
        return SimpleNamespace(id=USER_ID)

    mock_service = MagicMock()
    async def _mock_service() -> MagicMock:
        return mock_service

    app.dependency_overrides[get_current_org] = _mock_org
    app.dependency_overrides[get_current_user] = _mock_user
    app.dependency_overrides[get_shorts_render_service] = _mock_service
    app.dependency_overrides[get_scene_opensearch_client] = lambda: mock_scene_client

    return app


def _mock_scene_client(scene_doc: dict | None, scene_id: str = "scene_001") -> MagicMock:
    client = MagicMock()
    doc_id = f"{ORG_ID}:{scene_id}"
    if scene_doc is not None:
        client.mget_scenes = AsyncMock(return_value={doc_id: scene_doc})
    else:
        client.mget_scenes = AsyncMock(return_value={})
    return client


class TestSubtitleSuggestions:
    def test_full_metadata(self) -> None:
        """Scene with product_tags + keyword_tags + transcript → all returned."""
        sc = _mock_scene_client({
            "product_tags": ["립스틱", "파운데이션"],
            "keyword_tags": ["뷰티", "메이크업"],
            "transcript_raw": "안녕하세요 오늘은 립스틱 추천해드릴게요",
        })
        client = TestClient(_build_app(sc))

        resp = client.get("/api/shorts/render/suggestions/vid1/scene_001")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["suggestions"]) == 5  # 2 product + 2 keyword + 1 transcript

    def test_only_product_tags(self) -> None:
        sc = _mock_scene_client({
            "product_tags": ["립스틱"],
            "keyword_tags": [],
            "transcript_raw": "",
        })
        client = TestClient(_build_app(sc))

        resp = client.get("/api/shorts/render/suggestions/vid1/scene_001")
        assert resp.status_code == 200
        suggestions = resp.json()["suggestions"]
        assert len(suggestions) == 1
        assert suggestions[0]["source"] == "product_tag"

    def test_only_transcript(self) -> None:
        sc = _mock_scene_client({
            "product_tags": [],
            "keyword_tags": [],
            "transcript_raw": "오늘의 제품을 소개합니다",
        })
        client = TestClient(_build_app(sc))

        resp = client.get("/api/shorts/render/suggestions/vid1/scene_001")
        suggestions = resp.json()["suggestions"]
        assert len(suggestions) == 1
        assert suggestions[0]["source"] == "transcript"

    def test_empty_metadata(self) -> None:
        sc = _mock_scene_client({
            "product_tags": [],
            "keyword_tags": [],
            "transcript_raw": "",
        })
        client = TestClient(_build_app(sc))

        resp = client.get("/api/shorts/render/suggestions/vid1/scene_001")
        assert resp.json()["suggestions"] == []

    def test_scene_not_found_returns_404(self) -> None:
        sc = _mock_scene_client(None)
        client = TestClient(_build_app(sc))

        resp = client.get("/api/shorts/render/suggestions/vid1/scene_001")
        assert resp.status_code == 404

    def test_wrong_org_returns_404(self) -> None:
        """Scene from another org → doc_id won't match → 404."""
        client_mock = MagicMock()
        # Return a scene but under a different org's doc_id
        other_org = uuid4()
        client_mock.mget_scenes = AsyncMock(return_value={
            f"{other_org}:scene_001": {"product_tags": ["test"]},
        })
        client = TestClient(_build_app(client_mock))

        resp = client.get("/api/shorts/render/suggestions/vid1/scene_001")
        assert resp.status_code == 404

    def test_without_auth_returns_401(self) -> None:
        from fastapi import HTTPException, status as http_status

        app = FastAPI()
        app.include_router(shorts_render_router, prefix="/api")

        async def _mock_org() -> OrgContext:
            return OrgContext(org_id=ORG_ID, org_slug="testorg")

        async def _no_auth():
            raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED)

        app.dependency_overrides[get_current_org] = _mock_org
        app.dependency_overrides[get_current_user] = _no_auth
        app.dependency_overrides[get_shorts_render_service] = lambda: MagicMock()
        app.dependency_overrides[get_scene_opensearch_client] = lambda: MagicMock()

        client = TestClient(app)
        resp = client.get("/api/shorts/render/suggestions/vid1/scene_001")
        assert resp.status_code == 401

    def test_deduplication(self) -> None:
        """Tag appearing in both product_tags and keyword_tags → appears once."""
        sc = _mock_scene_client({
            "product_tags": ["립스틱"],
            "keyword_tags": ["립스틱", "뷰티"],
            "transcript_raw": "",
        })
        client = TestClient(_build_app(sc))

        resp = client.get("/api/shorts/render/suggestions/vid1/scene_001")
        suggestions = resp.json()["suggestions"]
        texts = [s["text"] for s in suggestions]
        assert texts.count("립스틱") == 1
        assert len(suggestions) == 2  # 립스틱 (product) + 뷰티 (keyword)

    def test_transcript_truncation(self) -> None:
        """Long transcript truncated to 50 chars."""
        long_text = "가" * 100
        sc = _mock_scene_client({
            "product_tags": [],
            "keyword_tags": [],
            "transcript_raw": long_text,
        })
        client = TestClient(_build_app(sc))

        resp = client.get("/api/shorts/render/suggestions/vid1/scene_001")
        suggestions = resp.json()["suggestions"]
        assert len(suggestions[0]["text"]) == 50

    def test_ordering_product_before_keyword_before_transcript(self) -> None:
        sc = _mock_scene_client({
            "product_tags": ["제품A"],
            "keyword_tags": ["키워드B"],
            "transcript_raw": "대본 텍스트",
        })
        client = TestClient(_build_app(sc))

        resp = client.get("/api/shorts/render/suggestions/vid1/scene_001")
        suggestions = resp.json()["suggestions"]
        assert suggestions[0]["source"] == "product_tag"
        assert suggestions[1]["source"] == "keyword_tag"
        assert suggestions[2]["source"] == "transcript"
