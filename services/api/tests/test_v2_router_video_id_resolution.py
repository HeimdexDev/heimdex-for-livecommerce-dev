"""Tests for OS-style video_id (`gd_xxx`) resolution across the v2
shorts-auto-product router endpoints.

PR #130 fixed the wizard's ``create_scan_order``; this file extends
the same fix to the other five endpoints (``get_product_catalog``,
``enqueue_scan``, ``enqueue_clip``, ``force_rescan``,
``reject_catalog_entry``) which all carried the same latent
``video_id: UUID`` typing.

All endpoints now share a single ``_resolve_video_uuid`` helper.
This file pins the post-fix shape per endpoint:
  * happy path: OS string at the path → DriveFile lookup →
    service receives the UUID.
  * 404 on missing/soft-deleted video.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _build_app(monkeypatch, *, drive_file: Any = None):
    """Mounts the public router with DriveFileRepository + service mocked.

    Returns ``(app, fake_drive_repo, fake_service, org_id)`` so each
    test can assert against the mocks without recreating fixtures.
    """
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

    # Build real Pydantic response instances — FastAPI validates the
    # response_model against the returned object, so MagicMocks with a
    # model_dump lambda fail with `uuid_type` errors. Constructing the
    # actual schemas keeps the test focused on the routing surface.
    from app.modules.shorts_auto_product.schemas import (
        ClipResponse,
        ProductCatalogResponse,
        RescanResponse,
        ScanResponse,
    )

    fake_service = MagicMock()
    fake_service.list_products = AsyncMock(return_value=ProductCatalogResponse(
        video_id=uuid4(),
        scan_status="never",
        scan_job_id=None,
        products=[],
    ))
    fake_service.enqueue_scan = AsyncMock(return_value=ScanResponse(
        job_id=uuid4(), deduped=False,
    ))
    fake_service.enqueue_clip = AsyncMock(return_value=ClipResponse(
        job_id=uuid4(), deduped=False, render_job_id=None,
    ))
    fake_service.rescan = AsyncMock(return_value=RescanResponse(
        job_id=uuid4(), invalidated_count=0,
    ))
    fake_service.reject_catalog_entry = AsyncMock(return_value=None)

    import app.modules.shorts_auto_product.router as router_module
    monkeypatch.setattr(
        router_module, "_build_service", lambda _db, _settings: fake_service,
    )

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


# ---------------------------------------------------------------------
# Per-endpoint OS-string resolution (happy path)
# ---------------------------------------------------------------------


def test_get_product_catalog_resolves_os_video_id(monkeypatch):
    drive_file_uuid = uuid4()
    drive_file = MagicMock(id=drive_file_uuid)
    app, _, fake_service, _ = _build_app(monkeypatch, drive_file=drive_file)
    client = TestClient(app)
    resp = client.get("/api/shorts/auto/products/gd_abc123")
    assert resp.status_code == 200, resp.text
    fake_service.list_products.assert_awaited_once()
    assert (
        fake_service.list_products.await_args.kwargs["video_id"]
        == drive_file_uuid
    )


def test_enqueue_scan_resolves_os_video_id(monkeypatch):
    drive_file_uuid = uuid4()
    app, _, fake_service, _ = _build_app(
        monkeypatch, drive_file=MagicMock(id=drive_file_uuid),
    )
    resp = TestClient(app).post(
        "/api/shorts/auto/products/gd_abc123/scan",
        json={"duration_preset_sec": 60},
    )
    assert resp.status_code == 202, resp.text
    fake_service.enqueue_scan.assert_awaited_once()
    assert (
        fake_service.enqueue_scan.await_args.kwargs["video_id"]
        == drive_file_uuid
    )


def test_enqueue_clip_resolves_os_video_id(monkeypatch):
    drive_file_uuid = uuid4()
    catalog_entry_id = uuid4()
    app, _, fake_service, _ = _build_app(
        monkeypatch, drive_file=MagicMock(id=drive_file_uuid),
    )
    resp = TestClient(app).post(
        f"/api/shorts/auto/products/gd_abc123/{catalog_entry_id}/clip",
        json={"duration_preset_sec": 60},
    )
    assert resp.status_code == 202, resp.text
    fake_service.enqueue_clip.assert_awaited_once()
    kwargs = fake_service.enqueue_clip.await_args.kwargs
    assert kwargs["video_id"] == drive_file_uuid
    assert kwargs["catalog_entry_id"] == catalog_entry_id


def test_force_rescan_resolves_os_video_id(monkeypatch):
    drive_file_uuid = uuid4()
    app, _, fake_service, _ = _build_app(
        monkeypatch, drive_file=MagicMock(id=drive_file_uuid),
    )
    resp = TestClient(app).post(
        "/api/shorts/auto/products/gd_abc123/rescan",
        json={"duration_preset_sec": 60},
    )
    assert resp.status_code == 202, resp.text
    fake_service.rescan.assert_awaited_once()
    assert (
        fake_service.rescan.await_args.kwargs["video_id"] == drive_file_uuid
    )


def test_reject_catalog_entry_resolves_os_video_id(monkeypatch):
    drive_file_uuid = uuid4()
    catalog_entry_id = uuid4()
    app, _, fake_service, _ = _build_app(
        monkeypatch, drive_file=MagicMock(id=drive_file_uuid),
    )
    resp = TestClient(app).delete(
        f"/api/shorts/auto/products/gd_abc123/{catalog_entry_id}",
    )
    assert resp.status_code == 204
    fake_service.reject_catalog_entry.assert_awaited_once()
    kwargs = fake_service.reject_catalog_entry.await_args.kwargs
    assert kwargs["video_id"] == drive_file_uuid
    assert kwargs["catalog_entry_id"] == catalog_entry_id


# ---------------------------------------------------------------------
# 404 on missing video (single representative test — same code path
# via the shared _resolve_video_uuid helper, so per-endpoint coverage
# would be redundant)
# ---------------------------------------------------------------------


def test_resolve_helper_returns_404_on_missing_video(monkeypatch):
    """When ``DriveFileRepository.get_by_video_id`` returns None, the
    helper raises HTTPException 404 — exercised here via
    ``get_product_catalog`` but the same code path runs on every
    endpoint that uses the helper."""
    app, _, fake_service, _ = _build_app(monkeypatch, drive_file=None)
    resp = TestClient(app).get("/api/shorts/auto/products/gd_does_not_exist")
    assert resp.status_code == 404
    assert "not found" in resp.text
    fake_service.list_products.assert_not_awaited()
