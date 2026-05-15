"""Tests for shorts render download endpoint."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_shorts_render_service
from app.modules.auth import get_current_user
from app.modules.shorts_render.router import router as shorts_render_router
from app.modules.shorts_render.service import ShortsRenderService
from app.modules.tenancy import OrgContext, get_current_org


ORG_ID = uuid4()
USER_ID = uuid4()
JOB_ID = uuid4()


def _fake_job(
    *,
    status: str = "completed",
    output_s3_key: str | None = "org/shorts/renders/job/output.mp4",
    job_id=None,
) -> SimpleNamespace:
    """Simulates a ShortsRenderJob DB record."""
    return SimpleNamespace(
        id=job_id or JOB_ID,
        org_id=ORG_ID,
        video_id="vid-1",
        title="Test",
        status=status,
        output_s3_key=output_s3_key,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc) if status == "completed" else None,
        render_time_ms=5000,
        output_duration_ms=10000,
        output_size_bytes=1024000,
        error=None,
    )


def _build_app(mock_service: MagicMock) -> FastAPI:
    app = FastAPI()
    app.include_router(shorts_render_router, prefix="/api")

    async def _mock_org() -> OrgContext:
        return OrgContext(org_id=ORG_ID, org_slug="testorg")

    async def _mock_user() -> SimpleNamespace:
        return SimpleNamespace(id=USER_ID)

    async def _mock_service_fn() -> MagicMock:
        return mock_service

    app.dependency_overrides[get_current_org] = _mock_org
    app.dependency_overrides[get_current_user] = _mock_user
    app.dependency_overrides[get_shorts_render_service] = _mock_service_fn

    return app


def _mock_s3_head(total_size: int = 1024000):
    """Returns a mock that patches S3Client for head_object."""
    mock_s3_cls = MagicMock()
    mock_s3_instance = MagicMock()
    mock_s3_cls.return_value = mock_s3_instance
    mock_s3_instance.bucket = "test-bucket"
    mock_s3_instance._client.head_object.return_value = {
        "ContentLength": total_size,
        "ContentType": "video/mp4",
    }
    # get_object returns streaming body
    mock_body = MagicMock()
    mock_body.read.side_effect = [b"x" * 1000, b""]
    mock_body.close = MagicMock()
    mock_s3_instance._client.get_object.return_value = {"Body": mock_body}
    return mock_s3_cls, mock_s3_instance


class TestDownloadEndpoint:
    @patch("app.storage.s3.S3Client")
    @patch("app.config.get_settings")
    def test_happy_path_full_download(self, mock_settings, mock_s3_cls) -> None:
        mock_settings.return_value = MagicMock(drive_s3_bucket="test-bucket")
        _, mock_s3 = _mock_s3_head(1024000)
        mock_s3_cls.return_value = mock_s3

        svc = MagicMock(spec=ShortsRenderService)
        svc.get_render_job_record = AsyncMock(return_value=_fake_job())
        client = TestClient(_build_app(svc))

        resp = client.get(f"/api/shorts/render/{JOB_ID}/download")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "video/mp4"

    @patch("app.storage.s3.S3Client")
    @patch("app.config.get_settings")
    def test_content_disposition(self, mock_settings, mock_s3_cls) -> None:
        mock_settings.return_value = MagicMock(drive_s3_bucket="test-bucket")
        _, mock_s3 = _mock_s3_head()
        mock_s3_cls.return_value = mock_s3

        svc = MagicMock(spec=ShortsRenderService)
        svc.get_render_job_record = AsyncMock(return_value=_fake_job())
        client = TestClient(_build_app(svc))

        resp = client.get(f"/api/shorts/render/{JOB_ID}/download")
        assert "attachment" in resp.headers.get("content-disposition", "")
        assert f"short_{JOB_ID}.mp4" in resp.headers["content-disposition"]

    @patch("app.storage.s3.S3Client")
    @patch("app.config.get_settings")
    def test_accept_ranges_header(self, mock_settings, mock_s3_cls) -> None:
        mock_settings.return_value = MagicMock(drive_s3_bucket="test-bucket")
        _, mock_s3 = _mock_s3_head()
        mock_s3_cls.return_value = mock_s3

        svc = MagicMock(spec=ShortsRenderService)
        svc.get_render_job_record = AsyncMock(return_value=_fake_job())
        client = TestClient(_build_app(svc))

        resp = client.get(f"/api/shorts/render/{JOB_ID}/download")
        assert resp.headers.get("accept-ranges") == "bytes"

    def test_queued_job_returns_409(self) -> None:
        svc = MagicMock(spec=ShortsRenderService)
        svc.get_render_job_record = AsyncMock(return_value=_fake_job(status="queued"))
        client = TestClient(_build_app(svc))

        resp = client.get(f"/api/shorts/render/{JOB_ID}/download")
        assert resp.status_code == 409

    def test_failed_job_returns_409(self) -> None:
        svc = MagicMock(spec=ShortsRenderService)
        svc.get_render_job_record = AsyncMock(return_value=_fake_job(status="failed", output_s3_key=None))
        client = TestClient(_build_app(svc))

        resp = client.get(f"/api/shorts/render/{JOB_ID}/download")
        assert resp.status_code == 409

    def test_no_output_s3_key_returns_409(self) -> None:
        svc = MagicMock(spec=ShortsRenderService)
        svc.get_render_job_record = AsyncMock(return_value=_fake_job(output_s3_key=None))
        client = TestClient(_build_app(svc))

        resp = client.get(f"/api/shorts/render/{JOB_ID}/download")
        assert resp.status_code == 409

    def test_nonexistent_job_returns_404(self) -> None:
        svc = MagicMock(spec=ShortsRenderService)
        svc.get_render_job_record = AsyncMock(return_value=None)
        client = TestClient(_build_app(svc))

        resp = client.get(f"/api/shorts/render/{JOB_ID}/download")
        assert resp.status_code == 404

    @patch("app.storage.s3.S3Client")
    @patch("app.config.get_settings")
    def test_range_request_returns_206(self, mock_settings, mock_s3_cls) -> None:
        mock_settings.return_value = MagicMock(drive_s3_bucket="test-bucket")
        _, mock_s3 = _mock_s3_head(10000)
        mock_s3_cls.return_value = mock_s3

        svc = MagicMock(spec=ShortsRenderService)
        svc.get_render_job_record = AsyncMock(return_value=_fake_job())
        client = TestClient(_build_app(svc))

        resp = client.get(
            f"/api/shorts/render/{JOB_ID}/download",
            headers={"Range": "bytes=0-999"},
        )
        assert resp.status_code == 206
        assert "content-range" in resp.headers
        assert resp.headers["content-range"].startswith("bytes 0-999/")

    @patch("app.storage.s3.S3Client")
    @patch("app.config.get_settings")
    def test_open_ended_range(self, mock_settings, mock_s3_cls) -> None:
        mock_settings.return_value = MagicMock(drive_s3_bucket="test-bucket")
        _, mock_s3 = _mock_s3_head(10000)
        mock_s3_cls.return_value = mock_s3

        svc = MagicMock(spec=ShortsRenderService)
        svc.get_render_job_record = AsyncMock(return_value=_fake_job())
        client = TestClient(_build_app(svc))

        resp = client.get(
            f"/api/shorts/render/{JOB_ID}/download",
            headers={"Range": "bytes=1000-"},
        )
        assert resp.status_code == 206

    @patch("app.storage.s3.S3Client")
    @patch("app.config.get_settings")
    def test_invalid_range_returns_416(self, mock_settings, mock_s3_cls) -> None:
        mock_settings.return_value = MagicMock(drive_s3_bucket="test-bucket")
        _, mock_s3 = _mock_s3_head(1000)
        mock_s3_cls.return_value = mock_s3

        svc = MagicMock(spec=ShortsRenderService)
        svc.get_render_job_record = AsyncMock(return_value=_fake_job())
        client = TestClient(_build_app(svc))

        resp = client.get(
            f"/api/shorts/render/{JOB_ID}/download",
            headers={"Range": "bytes=2000-3000"},
        )
        assert resp.status_code == 416

    @patch("app.storage.s3.S3Client")
    @patch("app.config.get_settings")
    def test_no_range_returns_200(self, mock_settings, mock_s3_cls) -> None:
        mock_settings.return_value = MagicMock(drive_s3_bucket="test-bucket")
        _, mock_s3 = _mock_s3_head(5000)
        mock_s3_cls.return_value = mock_s3

        svc = MagicMock(spec=ShortsRenderService)
        svc.get_render_job_record = AsyncMock(return_value=_fake_job())
        client = TestClient(_build_app(svc))

        resp = client.get(f"/api/shorts/render/{JOB_ID}/download")
        assert resp.status_code == 200
        assert resp.headers.get("content-length") == "5000"

    @patch("app.storage.s3.S3Client")
    @patch("app.config.get_settings")
    def test_s3_error_returns_502(self, mock_settings, mock_s3_cls) -> None:
        mock_settings.return_value = MagicMock(drive_s3_bucket="test-bucket")
        mock_s3 = MagicMock()
        mock_s3.bucket = "test-bucket"
        mock_s3._client.head_object.side_effect = Exception("S3 unreachable")
        mock_s3_cls.return_value = mock_s3

        svc = MagicMock(spec=ShortsRenderService)
        svc.get_render_job_record = AsyncMock(return_value=_fake_job())
        client = TestClient(_build_app(svc))

        resp = client.get(f"/api/shorts/render/{JOB_ID}/download")
        assert resp.status_code == 502
