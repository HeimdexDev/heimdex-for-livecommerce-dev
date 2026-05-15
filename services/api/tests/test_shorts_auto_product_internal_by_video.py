"""Phase 4 PR #5b — internal ``GET /internal/products/by-video/{video_id}``
endpoint tests.

Worker uses this endpoint in the wizard parent flow to enumerate the
active catalog entries for a video before running the per-product
track loop. Pattern A scoping (X-Heimdex-Org-Id header required) since
list queries can't use Pattern B's resource-id resolution.

NOT in CI allowlist (consistent with the rest of the
test_shorts_auto_product_*.py suite).
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


def _catalog_entry(
    *,
    entry_id: UUID,
    org_id: UUID,
    video_id: UUID,
    canonical_crop_s3_key: str = "products/org/video/abc.jpg",
    canonical_bbox: tuple[int, int, int, int] = (10, 20, 100, 150),
    llm_label: str = "핑크 세럼 병",
):
    obj = MagicMock()
    obj.id = entry_id
    obj.org_id = org_id
    obj.video_id = video_id
    obj.canonical_crop_s3_key = canonical_crop_s3_key
    obj.canonical_bbox_x = canonical_bbox[0]
    obj.canonical_bbox_y = canonical_bbox[1]
    obj.canonical_bbox_w = canonical_bbox[2]
    obj.canonical_bbox_h = canonical_bbox[3]
    obj.llm_label = llm_label
    return obj


@pytest.fixture
def _build_app(monkeypatch):
    def _factory(*, entries: list, internal_token: str = "test-internal-token"):
        from app.dependencies import get_db_session, verify_internal_token

        fake_repo = MagicMock()
        fake_repo.list_active_by_video = AsyncMock(return_value=entries)

        # Pattern B test patching (D53): patch BOTH the package re-export
        # AND the internal_router-bound name.
        import app.modules.shorts_auto_product.repositories.catalog as catalog_repo_module
        import app.modules.shorts_auto_product.repositories as repos_pkg
        import app.modules.shorts_auto_product.internal_router as router_module

        for module in (catalog_repo_module, repos_pkg, router_module):
            monkeypatch.setattr(
                module,
                "ProductCatalogRepository",
                MagicMock(return_value=fake_repo),
            )

        app = FastAPI()
        app.include_router(internal_router)
        fake_db = MagicMock()
        app.dependency_overrides[get_db_session] = lambda: fake_db
        app.dependency_overrides[verify_internal_token] = lambda: internal_token
        return app

    return _factory


def test_by_video_returns_active_entries(_build_app):
    org_id = uuid4()
    video_id = uuid4()
    entries = [
        _catalog_entry(
            entry_id=uuid4(), org_id=org_id, video_id=video_id,
            llm_label="lipstick",
        ),
        _catalog_entry(
            entry_id=uuid4(), org_id=org_id, video_id=video_id,
            llm_label="serum",
        ),
    ]
    app = _build_app(entries=entries)
    client = TestClient(app)
    resp = client.get(
        f"/internal/products/by-video/{video_id}",
        headers={
            "Authorization": "Bearer test-internal-token",
            "X-Heimdex-Org-Id": str(org_id),
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["org_id"] == str(org_id)
    assert body["video_id"] == str(video_id)
    assert len(body["entries"]) == 2
    labels = {e["llm_label"] for e in body["entries"]}
    assert labels == {"lipstick", "serum"}


def test_by_video_empty_catalog_returns_empty_list(_build_app):
    org_id = uuid4()
    video_id = uuid4()
    app = _build_app(entries=[])
    client = TestClient(app)
    resp = client.get(
        f"/internal/products/by-video/{video_id}",
        headers={
            "Authorization": "Bearer test-internal-token",
            "X-Heimdex-Org-Id": str(org_id),
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["entries"] == []


def test_by_video_missing_org_header_400(_build_app):
    video_id = uuid4()
    app = _build_app(entries=[])
    client = TestClient(app)
    resp = client.get(
        f"/internal/products/by-video/{video_id}",
        headers={"Authorization": "Bearer test-internal-token"},
    )
    assert resp.status_code == 400
    assert "X-Heimdex-Org-Id" in resp.text


def test_by_video_invalid_org_uuid_400(_build_app):
    video_id = uuid4()
    app = _build_app(entries=[])
    client = TestClient(app)
    resp = client.get(
        f"/internal/products/by-video/{video_id}",
        headers={
            "Authorization": "Bearer test-internal-token",
            "X-Heimdex-Org-Id": "not-a-uuid",
        },
    )
    assert resp.status_code == 400
    assert "valid UUID" in resp.text


def test_by_video_response_shape_matches_catalog_entry_resource(_build_app):
    """Each entry has the same shape as ``GET /catalog/{id}`` so the
    worker's per-product loop takes uniform input."""
    org_id = uuid4()
    video_id = uuid4()
    entry_id = uuid4()
    entries = [
        _catalog_entry(
            entry_id=entry_id, org_id=org_id, video_id=video_id,
            canonical_bbox=(15, 25, 200, 300),
            llm_label="primer",
        ),
    ]
    app = _build_app(entries=entries)
    client = TestClient(app)
    resp = client.get(
        f"/internal/products/by-video/{video_id}",
        headers={
            "Authorization": "Bearer test-internal-token",
            "X-Heimdex-Org-Id": str(org_id),
        },
    )
    assert resp.status_code == 200, resp.text
    entry = resp.json()["entries"][0]
    assert entry["catalog_entry_id"] == str(entry_id)
    assert entry["org_id"] == str(org_id)
    assert entry["video_id"] == str(video_id)
    assert entry["canonical_bbox"] == {"x": 15, "y": 25, "w": 200, "h": 300}
    assert entry["llm_label"] == "primer"


def test_by_video_calls_repo_with_correct_filters(_build_app):
    """Repo MUST be called with (org_id, video_id) — defense in depth
    against cross-tenant collision (codex Q3 family of issues)."""
    org_id = uuid4()
    video_id = uuid4()
    app = _build_app(entries=[])
    import app.modules.shorts_auto_product.repositories as repos_pkg
    fake_factory = repos_pkg.ProductCatalogRepository
    fake_repo = fake_factory(MagicMock())

    client = TestClient(app)
    resp = client.get(
        f"/internal/products/by-video/{video_id}",
        headers={
            "Authorization": "Bearer test-internal-token",
            "X-Heimdex-Org-Id": str(org_id),
        },
    )
    assert resp.status_code == 200
    fake_repo.list_active_by_video.assert_awaited_once()
    call_kwargs = fake_repo.list_active_by_video.await_args.kwargs
    assert call_kwargs["org_id"] == org_id
    assert call_kwargs["video_id"] == video_id
