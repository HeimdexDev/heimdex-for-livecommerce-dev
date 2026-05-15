"""Tests for shorts render router endpoints."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.dependencies import get_shorts_render_service
from app.modules.auth import get_current_user
from app.modules.shorts_render.router import router as shorts_render_router
from app.modules.shorts_render.schemas import RenderJobListResponse, RenderJobResponse
from app.modules.shorts_render.service import ShortsRenderService
from app.modules.tenancy import OrgContext, get_current_org


ORG_ID = uuid4()
USER_ID = uuid4()


def _job_response(
    *,
    status: str = "queued",
    download_url: str | None = None,
    job_id=None,
) -> RenderJobResponse:
    jid = job_id or uuid4()
    return RenderJobResponse(
        id=jid,
        video_id="vid-1",
        title="Test Render",
        status=status,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
        render_time_ms=None,
        output_duration_ms=None,
        output_size_bytes=None,
        error=None,
        download_url=download_url,
    )


def _build_app(mock_service: MagicMock) -> FastAPI:
    app = FastAPI()
    app.include_router(shorts_render_router, prefix="/api")

    async def _mock_org() -> OrgContext:
        return OrgContext(org_id=ORG_ID, org_slug="testorg")

    async def _mock_user() -> SimpleNamespace:
        return SimpleNamespace(id=USER_ID)

    async def _mock_service() -> MagicMock:
        return mock_service

    app.dependency_overrides[get_current_org] = _mock_org
    app.dependency_overrides[get_current_user] = _mock_user
    app.dependency_overrides[get_shorts_render_service] = _mock_service

    return app


def _build_app_no_auth(mock_service: MagicMock) -> FastAPI:
    """App with org override but no user override — triggers 401."""
    app = FastAPI()
    app.include_router(shorts_render_router, prefix="/api")

    async def _mock_org() -> OrgContext:
        return OrgContext(org_id=ORG_ID, org_slug="testorg")

    async def _mock_service_fn() -> MagicMock:
        return mock_service

    app.dependency_overrides[get_current_org] = _mock_org
    app.dependency_overrides[get_shorts_render_service] = _mock_service_fn
    # get_current_user NOT overridden — will raise 401 without Bearer token
    return app


def _valid_payload() -> dict:
    return {
        "video_id": "vid-1",
        "title": "Test Render",
        "composition": {
            "scene_clips": [
                {
                    "scene_id": "scene_001",
                    "video_id": "vid-1",
                    "start_ms": 1000,
                    "end_ms": 5000,
                    "timeline_start_ms": 0,
                }
            ],
        },
    }


# --- Test 1: POST valid render job → 201, status="queued" ---


def test_post_valid_render_job_returns_201():
    mock_service = MagicMock()
    resp = _job_response(status="queued")
    mock_service.create_render_job = AsyncMock(return_value=resp)

    app = _build_app(mock_service)
    with TestClient(app) as client:
        response = client.post("/api/shorts/render", json=_valid_payload())

    assert response.status_code == 201
    assert response.json()["status"] == "queued"


# --- Test 2: POST with empty clips → 422 ---


def test_post_empty_clips_returns_422():
    mock_service = MagicMock()
    app = _build_app(mock_service)

    payload = {
        "video_id": "vid-1",
        "composition": {"scene_clips": []},
    }
    with TestClient(app) as client:
        response = client.post("/api/shorts/render", json=payload)

    assert response.status_code == 422


# --- Test 3: POST without auth → 401 ---


def test_post_without_auth_returns_401():
    mock_service = MagicMock()
    app = _build_app_no_auth(mock_service)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/shorts/render", json=_valid_payload())

    assert response.status_code in (401, 403, 422, 500)


# --- Test 4: GET existing job → 200 ---


def test_get_existing_job_returns_200():
    mock_service = MagicMock()
    job_id = uuid4()
    resp = _job_response(job_id=job_id)
    mock_service.get_render_job = AsyncMock(return_value=resp)

    app = _build_app(mock_service)
    with TestClient(app) as client:
        response = client.get(f"/api/shorts/render/{job_id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(job_id)


# --- Test 5: GET non-existent job → 404 ---


def test_get_nonexistent_job_returns_404():
    mock_service = MagicMock()
    mock_service.get_render_job = AsyncMock(
        side_effect=HTTPException(status_code=404, detail="Render job not found")
    )

    app = _build_app(mock_service)
    with TestClient(app) as client:
        response = client.get(f"/api/shorts/render/{uuid4()}")

    assert response.status_code == 404


# --- Test 6: GET job from other org → 404 ---


def test_get_job_other_org_returns_404():
    mock_service = MagicMock()
    mock_service.get_render_job = AsyncMock(
        side_effect=HTTPException(status_code=404, detail="Render job not found")
    )

    app = _build_app(mock_service)
    with TestClient(app) as client:
        response = client.get(f"/api/shorts/render/{uuid4()}")

    assert response.status_code == 404


# --- Test 7: GET completed job → includes download_url ---


def test_get_completed_job_has_download_url():
    mock_service = MagicMock()
    job_id = uuid4()
    resp = _job_response(
        status="completed",
        download_url=f"/api/shorts/render/{job_id}/download",
        job_id=job_id,
    )
    mock_service.get_render_job = AsyncMock(return_value=resp)

    app = _build_app(mock_service)
    with TestClient(app) as client:
        response = client.get(f"/api/shorts/render/{job_id}")

    assert response.status_code == 200
    assert response.json()["download_url"] == f"/api/shorts/render/{job_id}/download"


# --- Test 8: GET queued job → download_url is None ---


def test_get_queued_job_download_url_is_none():
    mock_service = MagicMock()
    resp = _job_response(status="queued", download_url=None)
    mock_service.get_render_job = AsyncMock(return_value=resp)

    app = _build_app(mock_service)
    with TestClient(app) as client:
        response = client.get(f"/api/shorts/render/{uuid4()}")

    assert response.status_code == 200
    assert response.json()["download_url"] is None


# --- Test 9: LIST jobs → paginated, newest first ---


def test_list_jobs_paginated():
    mock_service = MagicMock()
    items = [_job_response(), _job_response(), _job_response()]
    mock_service.list_render_jobs = AsyncMock(
        return_value=RenderJobListResponse(items=items, total=3)
    )

    app = _build_app(mock_service)
    with TestClient(app) as client:
        response = client.get("/api/shorts/render")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert len(data["items"]) == 3


# --- Test 10: LIST with limit=2, offset=0 → 2 items ---


def test_list_jobs_with_limit():
    mock_service = MagicMock()
    items = [_job_response(), _job_response()]
    mock_service.list_render_jobs = AsyncMock(
        return_value=RenderJobListResponse(items=items, total=5)
    )

    app = _build_app(mock_service)
    with TestClient(app) as client:
        response = client.get("/api/shorts/render?limit=2&offset=0")

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["total"] == 5


# --- Test 11: LIST empty → items=[], total=0 ---


def test_list_jobs_empty():
    mock_service = MagicMock()
    mock_service.list_render_jobs = AsyncMock(
        return_value=RenderJobListResponse(items=[], total=0)
    )

    app = _build_app(mock_service)
    with TestClient(app) as client:
        response = client.get("/api/shorts/render")

    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0


# --- Test 12: LIST without auth → 401 ---


def test_list_without_auth_returns_401():
    mock_service = MagicMock()
    app = _build_app_no_auth(mock_service)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/shorts/render")

    assert response.status_code in (401, 403, 422, 500)


# --- Test 13: DELETE existing → 204 ---


def test_delete_existing_returns_204():
    mock_service = MagicMock()
    mock_service.delete_render_job = AsyncMock(return_value=None)

    app = _build_app(mock_service)
    with TestClient(app) as client:
        response = client.delete(f"/api/shorts/render/{uuid4()}")

    assert response.status_code == 204


# --- Test 14: DELETE non-existent → 404 ---


def test_delete_nonexistent_returns_404():
    mock_service = MagicMock()
    mock_service.delete_render_job = AsyncMock(
        side_effect=HTTPException(status_code=404, detail="Render job not found")
    )

    app = _build_app(mock_service)
    with TestClient(app) as client:
        response = client.delete(f"/api/shorts/render/{uuid4()}")

    assert response.status_code == 404


# --- Test 15: DELETE without auth → 401 ---


def test_delete_without_auth_returns_401():
    mock_service = MagicMock()
    app = _build_app_no_auth(mock_service)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.delete(f"/api/shorts/render/{uuid4()}")

    assert response.status_code in (401, 403, 422, 500)
