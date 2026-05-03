"""Tests for the wizard's create_scan_order video_id resolution.

Pre-fix the router accepted ``video_id: UUID`` at the path. The
frontend's ``/videos/{videoId}`` URL pattern uses the OS-style
``gd_xxx`` string, so every wizard submission from the video detail
page returned 422 ``uuid_parsing`` from FastAPI's path validator
before the handler ever ran.

This file pins the post-fix behavior:
  * OS string at the path resolves to the DriveFile, the service
    layer receives the UUID.
  * Missing / soft-deleted video → 404 (not 422), so the wizard
    can render a friendly message.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _build_app(monkeypatch, *, drive_file=None):
    """Build a minimal FastAPI app with the public router mounted +
    DriveFileRepository + ProductScanService mocked."""
    from app.dependencies import get_db_session
    from app.modules.shorts_auto_product.router import router

    fake_drive_repo = MagicMock()
    fake_drive_repo.get_by_video_id = AsyncMock(return_value=drive_file)

    import app.modules.drive.repository as drive_repo_module
    monkeypatch.setattr(
        drive_repo_module,
        "DriveFileRepository",
        MagicMock(side_effect=lambda _db: fake_drive_repo),
    )

    fake_service = MagicMock()
    fake_service.enqueue_scan_order = AsyncMock(
        return_value=MagicMock(
            parent_job_id=uuid4(),
            deduped=False,
            model_dump=lambda: {
                "parent_job_id": str(uuid4()),
                "deduped": False,
            },
        ),
    )
    import app.modules.shorts_auto_product.router as router_module
    monkeypatch.setattr(
        router_module, "_build_service", lambda _db, _settings: fake_service,
    )

    # Stub out auth + tenancy + settings so the router's deps resolve
    # without standing up real Auth0 + middleware.
    from app.modules.tenancy.middleware import get_current_org
    from app.modules.tenancy.context import OrgContext
    from app.modules.auth.service import get_current_user
    from app.config import get_settings as _get_settings

    org_id = uuid4()
    user_id = uuid4()
    fake_settings = MagicMock()
    fake_db = MagicMock()
    fake_db.commit = AsyncMock()

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api")
    test_app.dependency_overrides[get_db_session] = lambda: fake_db
    test_app.dependency_overrides[get_current_org] = lambda: OrgContext(
        org_id=org_id, org_slug="testorg",
    )
    test_app.dependency_overrides[get_current_user] = lambda: MagicMock(
        id=user_id,
    )
    test_app.dependency_overrides[_get_settings] = lambda: fake_settings

    return test_app, fake_drive_repo, fake_service, org_id


def _valid_body() -> dict:
    return {
        "length_seconds": 60,
        "requested_count": 5,
        "time_range_start_ms": None,
        "time_range_end_ms": None,
        "product_distribution": "single",
        "language": "ko",
        "intent": "commit",
    }


def test_create_scan_order_resolves_os_video_id_to_drive_file_uuid(
    monkeypatch,
):
    """**The 2026-05-03 staging-bug regression test.** OS-style
    video_id at the path must NOT 422 — the handler should look up
    the DriveFile and pass its UUID to the service."""
    drive_file_uuid = uuid4()
    drive_file = MagicMock(id=drive_file_uuid)
    app, fake_drive_repo, fake_service, org_id = _build_app(
        monkeypatch, drive_file=drive_file,
    )
    client = TestClient(app)
    resp = client.post(
        "/api/shorts/auto/scan-orders/videos/gd_d2e6142de1e19704",
        json=_valid_body(),
    )
    assert resp.status_code == 202, resp.text
    fake_drive_repo.get_by_video_id.assert_awaited_once_with(
        org_id=org_id, video_id="gd_d2e6142de1e19704",
    )
    # Service got the resolved UUID, not the OS string.
    fake_service.enqueue_scan_order.assert_awaited_once()
    call_kwargs = fake_service.enqueue_scan_order.await_args.kwargs
    assert call_kwargs["video_id"] == drive_file_uuid


def test_create_scan_order_returns_404_on_missing_video(monkeypatch):
    """Missing / soft-deleted DriveFile → 404 (not 422). Wizard
    surfaces this as a friendly message."""
    app, _, fake_service, _ = _build_app(monkeypatch, drive_file=None)
    client = TestClient(app)
    resp = client.post(
        "/api/shorts/auto/scan-orders/videos/gd_does_not_exist",
        json=_valid_body(),
    )
    assert resp.status_code == 404, resp.text
    assert "not found" in resp.text
    # Service was never reached.
    fake_service.enqueue_scan_order.assert_not_awaited()
