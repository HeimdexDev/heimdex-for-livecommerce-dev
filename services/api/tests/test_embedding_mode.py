from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import get_scene_search_service, get_search_service
from app.main import app
from app.modules.auth import get_current_user
from app.modules.tenancy import OrgContext, get_current_org


def _startup_patches():
    segment_client = MagicMock()
    segment_client.close = AsyncMock()

    scene_client = MagicMock()
    scene_client.close = AsyncMock()

    startup_engine = MagicMock()
    startup_engine.dispose = AsyncMock()

    return [
        patch("app.modules.search.client.OpenSearchClient", return_value=segment_client),
        patch("app.modules.search.scene_client.SceneSearchClient", return_value=scene_client),
        patch("app.db.base.get_async_engine", return_value=startup_engine),
        patch("app.main._startup_search_checks", new=AsyncMock()),
        patch("app.main._startup_scene_search_checks", new=AsyncMock()),
        patch("app.main._verify_org_auth0_bindings", new=AsyncMock()),
        patch("app.main._ensure_search_event_partitions", new=AsyncMock()),
    ]


def test_health_reports_mock_mode():
    mock_settings = Settings(embedding_use_mock=True, environment="development")

    startup_patchers = _startup_patches()
    with startup_patchers[0], startup_patchers[1], startup_patchers[2], startup_patchers[3], startup_patchers[4], startup_patchers[5], startup_patchers[6]:
        with patch("app.main.get_settings", return_value=mock_settings), patch("app.main.logger.warning") as mock_warning:
            with TestClient(app) as client:
                response = client.get("/health", headers={"host": "devorg.app.heimdex.local"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["embedding_mode"] == "mock"
    assert any(
        call.args and call.args[0] == "embedding_mock_mode_active"
        for call in mock_warning.call_args_list
    )


def test_health_reports_real_mode():
    mock_settings = Settings(embedding_use_mock=False)

    startup_patchers = _startup_patches()
    with startup_patchers[0], startup_patchers[1], startup_patchers[2], startup_patchers[3], startup_patchers[4], startup_patchers[5], startup_patchers[6]:
        with patch("app.main.get_settings", return_value=mock_settings), patch("app.main.logger.warning") as mock_warning:
            with TestClient(app) as client:
                response = client.get("/health", headers={"host": "devorg.app.heimdex.local"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["embedding_mode"] == "real"
    assert all(
        not (call.args and call.args[0] == "embedding_mock_mode_active")
        for call in mock_warning.call_args_list
    )


def test_search_returns_results_in_mock_mode():
    mock_settings = Settings(embedding_use_mock=True, environment="development")

    mock_search_service = MagicMock()
    mock_search_service.search = AsyncMock(
        return_value={
            "results": [{"segment_id": "seg-1"}],
            "total_candidates": 1,
            "query": "lip tint",
            "alpha": 0.5,
            "result_type": "segment",
        }
    )
    mock_scene_search_service = MagicMock()
    mock_scene_search_service.search = AsyncMock(return_value={"results": []})

    async def _mock_get_current_org() -> OrgContext:
        return OrgContext(org_id=uuid4(), org_slug="devorg")

    async def _mock_get_current_user() -> SimpleNamespace:
        return SimpleNamespace(id=uuid4())

    async def _mock_get_search_service() -> MagicMock:
        return mock_search_service

    async def _mock_get_scene_search_service() -> MagicMock:
        return mock_scene_search_service

    app.dependency_overrides[get_current_org] = _mock_get_current_org
    app.dependency_overrides[get_current_user] = _mock_get_current_user
    app.dependency_overrides[get_search_service] = _mock_get_search_service
    app.dependency_overrides[get_scene_search_service] = _mock_get_scene_search_service

    startup_patchers = _startup_patches()
    try:
        with startup_patchers[0], startup_patchers[1], startup_patchers[2], startup_patchers[3], startup_patchers[4], startup_patchers[5], startup_patchers[6]:
            with patch("app.main.get_settings", return_value=mock_settings):
                with TestClient(app) as client:
                    response = client.post(
                        "/api/search",
                        headers={"host": "devorg.app.heimdex.local"},
                        json={"q": "lip tint"},
                    )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert "results" in payload
    assert len(payload["results"]) == 1
    assert payload["results"][0]["segment_id"] == "seg-1"
    mock_search_service.search.assert_awaited_once()
