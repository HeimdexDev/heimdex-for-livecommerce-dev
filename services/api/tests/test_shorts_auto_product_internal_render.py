"""Phase 3c-B Item 3 — tests for the worker-facing render enqueue
endpoint:

* ``POST /internal/products/{job_id}/render``

Worker calls this immediately after building a stitch plan. Endpoint
checks lease ownership, validates the composition spec, then forwards
to ``ShortsRenderService.create_render_job(org_id, user_id,
RenderJobCreate)`` with org + user derived from the scan job row.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.shorts_auto_product.internal_router import (
    router as internal_router,
)


def _scan_job(
    *,
    job_id: UUID,
    org_id: UUID | None = None,
    requested_by_user_id: UUID | None = None,
    claimed_by: str | None = "worker-x",
    catalog_entry_id: UUID | None = None,
):
    obj = MagicMock()
    obj.id = job_id
    obj.org_id = org_id if org_id is not None else uuid4()
    obj.requested_by_user_id = (
        requested_by_user_id if requested_by_user_id is not None else uuid4()
    )
    obj.claimed_by = claimed_by
    # Default to a tracking job (catalog_entry_id is non-null);
    # tests that need an enum job override.
    obj.catalog_entry_id = (
        catalog_entry_id if catalog_entry_id is not None else uuid4()
    )
    return obj


def _composition() -> dict:
    """Minimal valid CompositionSpec dict."""
    return {
        "scene_clips": [
            {
                "scene_id": "gd_xyz_scene_001",
                "video_id": "gd_xyz",
                "source_type": "gdrive",
                "start_ms": 0,
                "end_ms": 5000,
                "timeline_start_ms": 0,
                "volume": 1.0,
            },
        ],
    }


@pytest.fixture
def _build_app(monkeypatch):
    def _factory(
        *,
        scan_job_obj,
        render_response_id: UUID | None = None,
        render_service_side_effect: Exception | None = None,
    ) -> tuple[FastAPI, MagicMock]:
        from app.dependencies import get_db_session, verify_internal_token

        # ProductScanJob lookup.
        fake_job_repo = MagicMock()
        fake_job_repo.get_internal = AsyncMock(return_value=scan_job_obj)
        import app.modules.shorts_auto_product.internal_router as ir
        monkeypatch.setattr(
            ir, "ProductScanJobRepository",
            MagicMock(return_value=fake_job_repo),
        )

        # ShortsRenderService.create_render_job — return a stub
        # response with .id, OR raise the requested exception.
        fake_service = MagicMock()
        if render_service_side_effect is not None:
            fake_service.create_render_job = AsyncMock(
                side_effect=render_service_side_effect,
            )
        else:
            response = MagicMock()
            response.id = render_response_id or uuid4()
            fake_service.create_render_job = AsyncMock(return_value=response)
        # The endpoint imports ``get_shorts_render_service`` lazily
        # inside the handler. Patch the dependency factory there.
        import app.dependencies as deps_module
        monkeypatch.setattr(
            deps_module,
            "get_shorts_render_service",
            lambda **_kwargs: fake_service,
        )

        app = FastAPI()
        app.include_router(internal_router)
        # AsyncMock so the await in the handler doesn't choke.
        fake_db = AsyncMock()
        app.dependency_overrides[get_db_session] = lambda: fake_db
        app.dependency_overrides[verify_internal_token] = lambda: "t"

        return app, fake_service

    return _factory


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer t"}


def _request_body(*, claimed_by: str = "worker-x", composition: dict | None = None) -> dict:
    return {
        "claimed_by": claimed_by,
        "payload": {
            "video_id": "gd_xyz",
            "title": "테스트 제품",
            "composition": composition or _composition(),
        },
    }


# ---------- happy path ----------


def test_enqueue_render_returns_render_job_id(_build_app):
    job_id = uuid4()
    render_id = uuid4()
    job = _scan_job(job_id=job_id, claimed_by="worker-x")
    app, service = _build_app(
        scan_job_obj=job, render_response_id=render_id,
    )

    with TestClient(app) as client:
        resp = client.post(
            f"/internal/products/{job_id}/render",
            json=_request_body(claimed_by="worker-x"),
            headers=_auth(),
        )
    assert resp.status_code == 201, resp.text
    assert resp.json() == {"render_job_id": str(render_id)}

    # Service was called with the scan job's org_id + user_id (NOT
    # values from the request body — server-of-record attribution).
    service.create_render_job.assert_called_once()
    kwargs = service.create_render_job.call_args.kwargs
    assert kwargs["org_id"] == job.org_id
    assert kwargs["user_id"] == job.requested_by_user_id


# ---------- error paths ----------


def test_enqueue_render_404_when_job_missing(_build_app):
    job_id = uuid4()
    app, service = _build_app(scan_job_obj=None)
    with TestClient(app) as client:
        resp = client.post(
            f"/internal/products/{job_id}/render",
            json=_request_body(),
            headers=_auth(),
        )
    assert resp.status_code == 404
    service.create_render_job.assert_not_called()


def test_enqueue_render_409_on_claimed_by_mismatch(_build_app):
    """Stale worker whose lease was reclaimed by another worker
    cannot enqueue renders for the new owner."""
    job_id = uuid4()
    job = _scan_job(job_id=job_id, claimed_by="worker-NEW")
    app, service = _build_app(scan_job_obj=job)

    with TestClient(app) as client:
        resp = client.post(
            f"/internal/products/{job_id}/render",
            json=_request_body(claimed_by="worker-STALE"),
            headers=_auth(),
        )
    assert resp.status_code == 409
    service.create_render_job.assert_not_called()


def test_enqueue_render_400_when_job_is_enumeration(_build_app):
    """Enumeration jobs don't render. A render enqueue from an
    enum job is a worker bug — surface with 400 rather than
    quietly creating a render row that has no associated catalog."""
    job_id = uuid4()
    job = _scan_job(
        job_id=job_id,
        claimed_by="worker-x",
        catalog_entry_id=None,  # enumeration job
    )
    # The MagicMock-default catalog_entry_id is a real UUID; need
    # to override with None to simulate enum.
    job.catalog_entry_id = None
    app, service = _build_app(scan_job_obj=job)

    with TestClient(app) as client:
        resp = client.post(
            f"/internal/products/{job_id}/render",
            json=_request_body(claimed_by="worker-x"),
            headers=_auth(),
        )
    assert resp.status_code == 400
    service.create_render_job.assert_not_called()


def test_enqueue_render_422_on_invalid_composition(_build_app):
    """Composition that fails ``CompositionSpec.model_validate``
    must 422 at the api boundary — never reach the service. Pins
    the wire-level validation contract."""
    job_id = uuid4()
    job = _scan_job(job_id=job_id, claimed_by="worker-x")
    app, service = _build_app(scan_job_obj=job)

    invalid_composition = {
        # CompositionSpec.scene_clips has min_length=1 — empty
        # list rejected.
        "scene_clips": [],
    }

    with TestClient(app) as client:
        resp = client.post(
            f"/internal/products/{job_id}/render",
            json=_request_body(composition=invalid_composition),
            headers=_auth(),
        )
    assert resp.status_code == 422
    service.create_render_job.assert_not_called()
