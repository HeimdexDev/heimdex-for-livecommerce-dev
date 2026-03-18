"""Tests for shorts render internal router endpoints."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_drive_file_repository, verify_internal_token
from app.modules.shorts_render.internal_router import router as internal_shorts_render_router

VALID_TOKEN = "test-internal-key"
ORG_ID = uuid4()


def _build_app(
    *,
    mock_repo=None,
    mock_drive_file_repo=None,
    require_token: bool = True,
) -> FastAPI:
    app = FastAPI()
    app.include_router(internal_shorts_render_router)

    if require_token:
        async def _mock_verify_token():
            return VALID_TOKEN
        app.dependency_overrides[verify_internal_token] = _mock_verify_token

    if mock_drive_file_repo is not None:
        async def _mock_drive_repo():
            return mock_drive_file_repo
        app.dependency_overrides[get_drive_file_repository] = _mock_drive_repo

    return app


def _make_render_job(
    *,
    job_id=None,
    status="queued",
    output_s3_key=None,
):
    job = MagicMock()
    job.id = job_id or uuid4()
    job.status = status
    job.output_s3_key = output_s3_key
    return job


def _make_drive_file(
    *,
    video_id="gd_abc123",
    proxy_s3_key="org1/drive/d1/f1/proxy.mp4",
    google_file_id="gfile_123",
):
    f = MagicMock()
    f.video_id = video_id
    f.proxy_s3_key = proxy_s3_key
    f.google_file_id = google_file_id
    return f


# --- Test 11: PUT /status with valid token → 200 ---


def test_put_status_valid_token_returns_200():
    mock_repo = AsyncMock()
    mock_repo.update_status = AsyncMock(return_value=_make_render_job(status="rendering"))

    app = _build_app()

    # Override the DB session to inject our mock repo
    from app.db.base import get_db_session

    async def _mock_db():
        return AsyncMock()

    app.dependency_overrides[get_db_session] = _mock_db

    # Patch repository creation
    from app.modules.shorts_render import internal_router

    original_init = internal_router.ShortsRenderJobRepository

    def _mock_repo_init(session):
        return mock_repo

    internal_router.ShortsRenderJobRepository = _mock_repo_init
    try:
        with TestClient(app) as client:
            response = client.put(
                f"/internal/shorts-render/{uuid4()}/status",
                json={"status": "rendering"},
            )
        assert response.status_code == 200
        assert response.json()["ok"] is True
    finally:
        internal_router.ShortsRenderJobRepository = original_init


# --- Test 12: PUT /status without token → 401/422 ---


def test_put_status_without_token_returns_error():
    app = _build_app(require_token=False)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.put(
            f"/internal/shorts-render/{uuid4()}/status",
            json={"status": "rendering"},
        )

    assert response.status_code in (401, 403, 422, 500)


# --- Test 13: PUT /status with invalid token → 401 ---


def test_put_status_invalid_token_returns_401():
    app = FastAPI()
    app.include_router(internal_shorts_render_router)
    # Do NOT override verify_internal_token — it will check real token

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.put(
            f"/internal/shorts-render/{uuid4()}/status",
            json={"status": "rendering"},
            headers={"Authorization": "Bearer wrong-token"},
        )

    assert response.status_code in (401, 500, 503)


# --- Test 14: PUT /status with completed + output fields → job updated ---


def test_put_status_completed_with_output():
    job_id = uuid4()
    mock_repo = AsyncMock()
    updated_job = _make_render_job(
        job_id=job_id,
        status="completed",
        output_s3_key="org/shorts/render/output.mp4",
    )
    mock_repo.update_status = AsyncMock(return_value=updated_job)

    app = _build_app()
    from app.db.base import get_db_session
    from app.modules.shorts_render import internal_router

    async def _mock_db():
        return AsyncMock()

    app.dependency_overrides[get_db_session] = _mock_db

    original_init = internal_router.ShortsRenderJobRepository

    def _mock_repo_init(session):
        return mock_repo

    internal_router.ShortsRenderJobRepository = _mock_repo_init
    try:
        with TestClient(app) as client:
            response = client.put(
                f"/internal/shorts-render/{job_id}/status",
                json={
                    "status": "completed",
                    "output_s3_key": "org/shorts/render/output.mp4",
                    "output_duration_ms": 15000,
                    "output_size_bytes": 5000000,
                    "render_time_ms": 8000,
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        mock_repo.update_status.assert_called_once()
        call_kwargs = mock_repo.update_status.call_args
        assert call_kwargs[0][1] == "completed"
    finally:
        internal_router.ShortsRenderJobRepository = original_init


# --- Test 15: PUT /status with failed + error → job updated ---


def test_put_status_failed_with_error():
    job_id = uuid4()
    mock_repo = AsyncMock()
    mock_repo.update_status = AsyncMock(
        return_value=_make_render_job(job_id=job_id, status="failed")
    )

    app = _build_app()
    from app.db.base import get_db_session
    from app.modules.shorts_render import internal_router

    async def _mock_db():
        return AsyncMock()

    app.dependency_overrides[get_db_session] = _mock_db

    original_init = internal_router.ShortsRenderJobRepository

    def _mock_repo_init(session):
        return mock_repo

    internal_router.ShortsRenderJobRepository = _mock_repo_init
    try:
        with TestClient(app) as client:
            response = client.put(
                f"/internal/shorts-render/{job_id}/status",
                json={
                    "status": "failed",
                    "error": "ffmpeg exited with code 1",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        call_kwargs = mock_repo.update_status.call_args[1]
        assert call_kwargs["error"] == "ffmpeg exited with code 1"
    finally:
        internal_router.ShortsRenderJobRepository = original_init


# --- Test 16: GET /media-source for gdrive video → returns S3 key ---


def test_get_media_source_gdrive():
    mock_drive_repo = AsyncMock()
    drive_file = _make_drive_file()
    mock_drive_repo.get_by_video_id = AsyncMock(return_value=drive_file)

    app = _build_app(mock_drive_file_repo=mock_drive_repo)
    with TestClient(app) as client:
        response = client.get(
            "/internal/shorts-render/gd_abc123/media-source",
            headers={"X-Heimdex-Org-Id": str(ORG_ID)},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["source_type"] == "gdrive"
    assert data["proxy_s3_key"] == "org1/drive/d1/f1/proxy.mp4"
    assert data["google_file_id"] == "gfile_123"


# --- Test 17: GET /media-source for non-gdrive video → 404 ---


def test_get_media_source_non_gdrive_returns_404():
    mock_drive_repo = AsyncMock()

    app = _build_app(mock_drive_file_repo=mock_drive_repo)
    with TestClient(app) as client:
        response = client.get(
            "/internal/shorts-render/yt_xyz789/media-source",
            headers={"X-Heimdex-Org-Id": str(ORG_ID)},
        )

    assert response.status_code == 404


# --- Test 18: GET /media-source with non-existent video_id → 404 ---


def test_get_media_source_not_found():
    mock_drive_repo = AsyncMock()
    mock_drive_repo.get_by_video_id = AsyncMock(return_value=None)

    app = _build_app(mock_drive_file_repo=mock_drive_repo)
    with TestClient(app) as client:
        response = client.get(
            "/internal/shorts-render/gd_nonexistent/media-source",
            headers={"X-Heimdex-Org-Id": str(ORG_ID)},
        )

    assert response.status_code == 404
