"""Tests for the Phase 3c-B internal catalog endpoint:

* ``GET /internal/products/catalog/{catalog_entry_id}``

Mirrors the Phase 3b ``test_videos_internal_phase3b.py`` test
harness — minimal FastAPI app + mocked repo deps so the routing /
auth / Pattern B logic is testable without DB or worker stack.

The track worker calls this immediately after claiming a track job
to fetch ``(canonical_crop_s3_key, canonical_bbox, llm_label)`` —
everything needed to seed SigLIP2 retrieval + SAM2 anchoring.
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
    org_id: UUID | None = None,
    video_id: UUID | None = None,
    canonical_crop_s3_key: str = "products/org/video/abc.jpg",
    canonical_bbox: tuple[int, int, int, int] = (10, 20, 100, 150),
    llm_label: str = "핑크 세럼 병",
):
    """Mocked ``ProductCatalogEntry`` row. ``resolve_resource_with_org``
    reads ``.org_id`` to derive tenant; the rest are response payload
    fields."""
    obj = MagicMock()
    obj.id = entry_id
    obj.org_id = org_id if org_id is not None else uuid4()
    obj.video_id = video_id if video_id is not None else uuid4()
    obj.canonical_crop_s3_key = canonical_crop_s3_key
    obj.canonical_bbox_x = canonical_bbox[0]
    obj.canonical_bbox_y = canonical_bbox[1]
    obj.canonical_bbox_w = canonical_bbox[2]
    obj.canonical_bbox_h = canonical_bbox[3]
    obj.llm_label = llm_label
    return obj


@pytest.fixture
def _build_app(monkeypatch):
    def _factory(
        *,
        catalog_entry_obj,
        internal_token: str = "test-internal-token",
    ) -> FastAPI:
        from app.dependencies import get_db_session, verify_internal_token

        fake_repo = MagicMock()
        fake_repo.get_by_id_resource_scoped = AsyncMock(
            return_value=catalog_entry_obj,
        )

        import app.modules.shorts_auto_product.repositories.catalog as catalog_repo_module
        # ``ProductCatalogRepository`` is also re-exported from
        # ``repositories/__init__.py``; the router imports the
        # symbol from there. Patch BOTH locations so the test
        # mock wins regardless of the call site's import path.
        monkeypatch.setattr(
            catalog_repo_module,
            "ProductCatalogRepository",
            MagicMock(return_value=fake_repo),
        )
        import app.modules.shorts_auto_product.repositories as repos_pkg
        monkeypatch.setattr(
            repos_pkg,
            "ProductCatalogRepository",
            MagicMock(return_value=fake_repo),
        )
        # The internal_router imports ProductCatalogRepository at
        # module-load time, so monkey-patching the package alone
        # doesn't reach the bound name. Patch the router's own
        # reference too.
        import app.modules.shorts_auto_product.internal_router as internal_router_module
        monkeypatch.setattr(
            internal_router_module,
            "ProductCatalogRepository",
            MagicMock(return_value=fake_repo),
        )

        app = FastAPI()
        app.include_router(internal_router)
        app.dependency_overrides[get_db_session] = lambda: AsyncMock()
        app.dependency_overrides[verify_internal_token] = lambda: internal_token
        return app

    return _factory


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-internal-token"}


# ---------- happy path ----------


def test_get_catalog_entry_returns_full_resource(_build_app):
    entry_id = uuid4()
    org_id = uuid4()
    video_id = uuid4()
    entry = _catalog_entry(
        entry_id=entry_id,
        org_id=org_id,
        video_id=video_id,
        canonical_crop_s3_key="products/X/Y/abc.jpg",
        canonical_bbox=(15, 25, 200, 300),
        llm_label="핑크 세럼 병",
    )
    app = _build_app(catalog_entry_obj=entry)

    with TestClient(app) as client:
        resp = client.get(
            f"/internal/products/catalog/{entry_id}",
            headers=_auth_headers(),
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["catalog_entry_id"] == str(entry_id)
    assert body["org_id"] == str(org_id)
    assert body["video_id"] == str(video_id)
    assert body["canonical_crop_s3_key"] == "products/X/Y/abc.jpg"
    assert body["canonical_bbox"] == {"x": 15, "y": 25, "w": 200, "h": 300}
    assert body["llm_label"] == "핑크 세럼 병"


def test_get_catalog_entry_works_without_org_header(_build_app):
    """Pattern B: header is optional. The path resource derives the
    org by itself, so omitting ``X-Heimdex-Org-Id`` is the new ideal
    pattern (the header path is back-compat cross-validation only)."""
    entry_id = uuid4()
    entry = _catalog_entry(entry_id=entry_id)
    app = _build_app(catalog_entry_obj=entry)

    with TestClient(app) as client:
        resp = client.get(
            f"/internal/products/catalog/{entry_id}",
            headers=_auth_headers(),
        )
    assert resp.status_code == 200, resp.text


# ---------- not found ----------


def test_get_catalog_entry_404_when_repo_returns_none(monkeypatch):
    """No row found in DB → 404 with the endpoint-specific detail
    string (NOT the generic Pattern B helper default)."""
    from app.dependencies import get_db_session, verify_internal_token

    fake_repo = MagicMock()
    fake_repo.get_by_id_resource_scoped = AsyncMock(return_value=None)
    import app.modules.shorts_auto_product.internal_router as ir
    monkeypatch.setattr(
        ir, "ProductCatalogRepository",
        MagicMock(return_value=fake_repo),
    )

    app = FastAPI()
    app.include_router(internal_router)
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()
    app.dependency_overrides[verify_internal_token] = lambda: "t"

    with TestClient(app) as client:
        resp = client.get(
            f"/internal/products/catalog/{uuid4()}",
            headers=_auth_headers(),
        )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "catalog entry not found"


def test_get_catalog_entry_404_on_cross_tenant_header_mismatch(_build_app):
    """When the header is provided AND mismatches the resource's
    org_id, response is 404 (NOT 403). Same response shape as
    not-found so timing doesn't reveal the entry's true tenant.
    Pattern B invariant — pinned by every Pattern B endpoint test."""
    entry_id = uuid4()
    real_org = uuid4()
    asserted_org = uuid4()  # different
    entry = _catalog_entry(entry_id=entry_id, org_id=real_org)
    app = _build_app(catalog_entry_obj=entry)

    with TestClient(app) as client:
        resp = client.get(
            f"/internal/products/catalog/{entry_id}",
            headers={
                **_auth_headers(),
                "X-Heimdex-Org-Id": str(asserted_org),
            },
        )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "catalog entry not found"


def test_get_catalog_entry_400_on_invalid_org_header(_build_app):
    """When the header is provided but isn't a valid UUID, the helper
    raises 400 (not 404) — distinguishes a malformed request from a
    cross-tenant attempt."""
    entry = _catalog_entry(entry_id=uuid4())
    app = _build_app(catalog_entry_obj=entry)

    with TestClient(app) as client:
        resp = client.get(
            f"/internal/products/catalog/{uuid4()}",
            headers={
                **_auth_headers(),
                "X-Heimdex-Org-Id": "not-a-uuid",
            },
        )
    assert resp.status_code == 400


# ---------- response shape ----------


def test_response_omits_embedding_and_score_fields(_build_app):
    """Defensive: the response model is ``extra='forbid'`` over a
    deliberately-minimal field set. Ensures over-projecting (e.g.
    accidentally including the 768-dim siglip2_embedding) is caught."""
    entry_id = uuid4()
    entry = _catalog_entry(entry_id=entry_id)
    # Stash extra fields the row might happen to carry — they MUST
    # not appear in the response.
    entry.siglip2_embedding = [0.5] * 768
    entry.enumeration_confidence = 0.87
    entry.prominence_score = 0.42
    app = _build_app(catalog_entry_obj=entry)

    with TestClient(app) as client:
        resp = client.get(
            f"/internal/products/catalog/{entry_id}",
            headers=_auth_headers(),
        )
    body = resp.json()
    assert "siglip2_embedding" not in body
    assert "enumeration_confidence" not in body
    assert "prominence_score" not in body
    # Pin the exact response key set so accidental drift is loud.
    assert set(body.keys()) == {
        "catalog_entry_id", "org_id", "video_id",
        "canonical_crop_s3_key", "canonical_bbox", "llm_label",
    }
