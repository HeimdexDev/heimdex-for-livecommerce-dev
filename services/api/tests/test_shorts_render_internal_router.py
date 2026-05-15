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
    org_id=None,
):
    f = MagicMock()
    f.video_id = video_id
    f.proxy_s3_key = proxy_s3_key
    f.google_file_id = google_file_id
    # Pattern B (post-2026-05-01): the endpoint derives org_id from
    # the resource. Default to the module-level ORG_ID so existing
    # tests asserting that header keep matching.
    f.org_id = org_id if org_id is not None else ORG_ID
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
    """Completed path uses ``complete_idempotent`` (PR 4 of whisper-subtitles).

    On did_flip=True the post_render_hook fires (no-op when flag is off,
    which is the default — confirmed by `assert_called_once`).
    """
    job_id = uuid4()
    existing_job = _make_render_job(job_id=job_id, status="rendering")
    existing_job.org_id = uuid4()
    mock_repo = AsyncMock()
    mock_repo._get_by_id_internal = AsyncMock(return_value=existing_job)
    mock_repo.complete_idempotent = AsyncMock(return_value=True)

    app = _build_app()
    from app.db.base import get_db_session
    from app.modules.shorts_render import internal_router

    mock_session = AsyncMock()

    async def _mock_db():
        return mock_session

    app.dependency_overrides[get_db_session] = _mock_db

    original_init = internal_router.ShortsRenderJobRepository
    original_hook = internal_router.post_render_hook.schedule_refinement_if_eligible

    def _mock_repo_init(session):
        return mock_repo

    hook_calls: list[dict] = []

    def _spy_hook(*, parent_job_id, org_id):
        hook_calls.append({"parent_job_id": parent_job_id, "org_id": org_id})

    internal_router.ShortsRenderJobRepository = _mock_repo_init
    internal_router.post_render_hook.schedule_refinement_if_eligible = _spy_hook
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
        # New idempotent path
        mock_repo._get_by_id_internal.assert_called_once_with(job_id)
        mock_repo.complete_idempotent.assert_called_once()
        ci_kwargs = mock_repo.complete_idempotent.call_args.kwargs
        assert ci_kwargs["output_s3_key"] == "org/shorts/render/output.mp4"
        assert ci_kwargs["output_duration_ms"] == 15000
        # update_status NOT called for completed status
        mock_repo.update_status.assert_not_called()
        # Explicit commit before scheduling the hook
        mock_session.commit.assert_awaited()
        # Hook fires exactly once on did_flip=True
        assert len(hook_calls) == 1
        assert hook_calls[0]["parent_job_id"] == job_id
        assert hook_calls[0]["org_id"] == existing_job.org_id
    finally:
        internal_router.ShortsRenderJobRepository = original_init
        internal_router.post_render_hook.schedule_refinement_if_eligible = (
            original_hook
        )


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
    mock_drive_repo.get_by_video_id_resource_scoped = AsyncMock(return_value=drive_file)

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
    mock_drive_repo.get_by_video_id_resource_scoped = AsyncMock(return_value=None)

    app = _build_app(mock_drive_file_repo=mock_drive_repo)
    with TestClient(app) as client:
        response = client.get(
            "/internal/shorts-render/gd_nonexistent/media-source",
            headers={"X-Heimdex-Org-Id": str(ORG_ID)},
        )

    assert response.status_code == 404


# --- /exists liveness probe (worker pre-render check) ---


def test_get_exists_returns_200_for_alive_job():
    job_id = uuid4()
    mock_repo = AsyncMock()
    mock_repo._get_by_id_internal = AsyncMock(
        return_value=_make_render_job(job_id=job_id, status="rendering"),
    )

    app = _build_app()
    from app.db.base import get_db_session
    from app.modules.shorts_render import internal_router

    async def _mock_db():
        return AsyncMock()

    app.dependency_overrides[get_db_session] = _mock_db

    original_init = internal_router.ShortsRenderJobRepository
    internal_router.ShortsRenderJobRepository = lambda session: mock_repo
    try:
        with TestClient(app) as client:
            response = client.get(f"/internal/shorts-render/{job_id}/exists")
        assert response.status_code == 200
        body = response.json()
        assert body["exists"] is True
        # Status echoes through so a future caller can branch on
        # terminal states without an extra round-trip.
        assert body["status"] == "rendering"
    finally:
        internal_router.ShortsRenderJobRepository = original_init


def test_get_exists_returns_404_when_row_deleted():
    """Worker pre-render check sees this 404 → ack + skip render."""
    job_id = uuid4()
    mock_repo = AsyncMock()
    mock_repo._get_by_id_internal = AsyncMock(return_value=None)

    app = _build_app()
    from app.db.base import get_db_session
    from app.modules.shorts_render import internal_router

    async def _mock_db():
        return AsyncMock()

    app.dependency_overrides[get_db_session] = _mock_db

    original_init = internal_router.ShortsRenderJobRepository
    internal_router.ShortsRenderJobRepository = lambda session: mock_repo
    try:
        with TestClient(app) as client:
            response = client.get(f"/internal/shorts-render/{job_id}/exists")
        assert response.status_code == 404
    finally:
        internal_router.ShortsRenderJobRepository = original_init


def test_get_exists_requires_internal_token():
    """No bearer → fail. Pattern B internal endpoints all require it."""
    app = FastAPI()
    app.include_router(internal_shorts_render_router)
    # Do NOT override verify_internal_token — real verifier runs.

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            f"/internal/shorts-render/{uuid4()}/exists",
            headers={"Authorization": "Bearer wrong-token"},
        )
    # Mirrors the existing PUT /status auth-failure assertion shape —
    # wrong/missing token returns 401 (or 500/503 if the verifier
    # itself errors out before auth resolution).
    assert response.status_code in (401, 500, 503)
