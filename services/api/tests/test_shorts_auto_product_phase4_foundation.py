"""Phase 4 foundation regression tests.

Codex-flagged work items from the Phase 4-7 plan §3.3:

* The dual-discriminator switch — ``_job_to_status_response`` and
  ``/complete`` MUST branch on ``mode``, not on
  ``catalog_entry_id IS NULL`` (which would misclassify
  ``mode='scan_order'`` parents).
* The ``find_recent_duplicate`` org_id defensive bug fix — the lookup
  was tenant-blind.
* The Q4 invariant that ``mode='scan_order'`` parents NEVER carry
  ``render_job_id`` in API responses (DB CHECK is the canonical
  enforcement; this test covers the response layer's defense in depth).

These tests are deliberately unit-scope (no Postgres) — DB CHECK
constraints are exercised by the alembic migration test in
``tests/test_alembic_migration_052_check_constraints.py`` (added in a
follow-up PR with integration markers).

NOT in the CI allowlist (yet) — same gating as the rest of the
``test_shorts_auto_product_*.py`` suite. Run locally:

    cd services/api && source .venv/bin/activate && pytest \\
        tests/test_shorts_auto_product_phase4_foundation.py
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.shorts_auto_product.models import (
    SCAN_MODE_ENUMERATE,
    SCAN_MODE_RENDER_CHILD,
    SCAN_MODE_SCAN_ORDER,
    SCAN_STAGE_DONE,
    SCAN_STAGE_QUEUED,
)
from app.modules.shorts_auto_product.service import _job_to_status_response


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------


def _job_row(
    *,
    job_id: UUID | None = None,
    mode: str = SCAN_MODE_ENUMERATE,
    catalog_entry_id: UUID | None = None,
    parent_job_id: UUID | None = None,
    shorts_index: int | None = None,
    render_job_id: UUID | None = None,
    stage: str = SCAN_STAGE_QUEUED,
):
    """Mocked ``ProductScanJob`` row.

    ``MagicMock`` mirrors SQLAlchemy ORM attribute access without
    needing a session or table. Only attributes ``_job_to_status_response``
    actually reads need to be present; the rest are auto-magicked.
    """
    job = MagicMock()
    job.id = job_id if job_id is not None else uuid4()
    job.mode = mode
    job.catalog_entry_id = catalog_entry_id
    job.parent_job_id = parent_job_id
    job.shorts_index = shorts_index
    job.render_job_id = render_job_id
    job.stage = stage
    job.progress_pct = 0
    job.progress_label = None
    job.completed_at = None
    job.failed_at = None
    job.cancelled_at = None
    job.error_code = None
    job.error_message = None
    job.cost_usd_estimate = Decimal("0")
    return job


# ======================================================================
# Q1.1 dual-discriminator switch — _job_to_status_response branches on
# mode, NOT on catalog_entry_id IS NULL
# ======================================================================


def test_status_response_enumerate_mode_no_catalog_entry_id():
    """``mode='enumerate'`` with ``catalog_entry_id=NULL`` → kind='enumeration'.

    This is the unchanged enumeration job path. Backward-compat baseline.
    """
    job = _job_row(mode=SCAN_MODE_ENUMERATE, catalog_entry_id=None)
    resp = _job_to_status_response(job)
    assert resp.kind == "enumeration"
    assert resp.parent_job_id is None
    assert resp.shorts_index is None


def test_status_response_enumerate_mode_with_catalog_entry_id():
    """``mode='enumerate'`` with ``catalog_entry_id`` set → kind='tracking'
    (legacy single-product flow during +4wk deprecation window)."""
    job = _job_row(
        mode=SCAN_MODE_ENUMERATE,
        catalog_entry_id=uuid4(),
        render_job_id=uuid4(),
    )
    resp = _job_to_status_response(job)
    assert resp.kind == "tracking"
    assert resp.render_job_id == job.render_job_id


def test_status_response_scan_order_mode_kind_and_render_job_id_masked():
    """**The codex-flagged Q4 regression**: ``mode='scan_order'`` parents
    must report ``kind='scan_order'`` AND **MUST NOT echo render_job_id**
    in the response, even if the row carries one (the
    ``ck_psj_parent_no_render`` CHECK should make that impossible at the
    DB level, but the response layer enforces it as defense in depth).
    """
    parent_id = uuid4()
    bogus_render_id = uuid4()
    job = _job_row(
        job_id=parent_id,
        mode=SCAN_MODE_SCAN_ORDER,
        catalog_entry_id=None,         # parents always NULL on this column
        # Force a non-NULL render_job_id on the row to verify the
        # response layer scrubs it. In production the DB CHECK would
        # prevent this from existing — we simulate the buggy state.
        render_job_id=bogus_render_id,
    )
    resp = _job_to_status_response(job)
    assert resp.kind == "scan_order"
    assert resp.render_job_id is None, (
        "scan_order parents must NEVER echo render_job_id in the "
        "response payload (Q4 codex pushback — defense in depth)"
    )


def test_status_response_render_child_mode_lineage_populated():
    """``mode='render_child'`` → kind='render_child' AND
    ``parent_job_id`` + ``shorts_index`` populated."""
    parent_id = uuid4()
    job = _job_row(
        mode=SCAN_MODE_RENDER_CHILD,
        catalog_entry_id=None,
        parent_job_id=parent_id,
        shorts_index=3,
        render_job_id=uuid4(),
    )
    resp = _job_to_status_response(job)
    assert resp.kind == "render_child"
    assert resp.parent_job_id == parent_id
    assert resp.shorts_index == 3
    assert resp.render_job_id == job.render_job_id


def test_status_response_unknown_mode_raises():
    """Defensive: an unknown mode (CHECK constraint should prevent this
    in production) should raise ValueError rather than silently
    misclassify."""
    job = _job_row(mode="banana")
    with pytest.raises(ValueError, match="unknown ProductScanJob.mode"):
        _job_to_status_response(job)


# ======================================================================
# Q3 — find_recent_duplicate org_id filter (codex defensive fix)
# ======================================================================


@pytest.mark.asyncio
async def test_find_recent_duplicate_filters_on_org_id():
    """Codex caught: pre-fix ``find_recent_duplicate`` did NOT filter
    on ``org_id``. Even though Postgres FK on video_id provides natural
    tenancy scoping, this is defense in depth — every other read in
    the module is org-scoped.

    Verifies the SQL statement built by the repository contains an
    ``org_id`` predicate.
    """
    from app.modules.shorts_auto_product.repositories.job import (
        ProductScanJobRepository,
    )

    captured_stmt = []

    class _StubResult:
        def scalar_one_or_none(self):
            return None

    async def _stub_execute(stmt):
        captured_stmt.append(stmt)
        return _StubResult()

    fake_session = MagicMock()
    fake_session.execute = AsyncMock(side_effect=_stub_execute)

    repo = ProductScanJobRepository(fake_session)
    await repo.find_recent_duplicate(
        org_id=uuid4(),
        video_id=uuid4(),
        user_id=uuid4(),
        catalog_entry_id=None,
        within_seconds=60,
    )

    assert len(captured_stmt) == 1
    rendered = str(
        captured_stmt[0].compile(compile_kwargs={"literal_binds": False})
    )
    assert "org_id" in rendered, (
        "find_recent_duplicate must filter on org_id (codex defensive "
        f"bug fix). Rendered SQL: {rendered}"
    )


# ======================================================================
# Q1.1 dual-discriminator switch — /complete branches on mode
# ======================================================================


def _build_complete_app(monkeypatch, *, job, persisted_appearance_count=0,
                       persisted_catalog_count=0):
    """Build a minimal FastAPI app with the internal router mounted +
    repos mocked. Pattern B test patching: stub both the package
    re-export AND the internal_router-bound name.
    """
    from app.dependencies import get_db_session, verify_internal_token
    from app.modules.shorts_auto_product.internal_router import (
        router as internal_router,
    )

    fake_job_repo = MagicMock()
    fake_job_repo.get_internal = AsyncMock(return_value=job)
    fake_job_repo.complete_enumeration = AsyncMock(return_value=job)
    fake_job_repo.complete_tracking = AsyncMock(return_value=job)

    fake_catalog_repo = MagicMock()
    catalog_rows = [MagicMock() for _ in range(persisted_catalog_count)]
    fake_catalog_repo.bulk_insert = AsyncMock(return_value=catalog_rows)

    fake_appearance_repo = MagicMock()
    appearance_rows = [MagicMock() for _ in range(persisted_appearance_count)]
    fake_appearance_repo.bulk_insert = AsyncMock(return_value=appearance_rows)

    fake_cost_repo = MagicMock()
    fake_cost_repo.add_cost = AsyncMock()

    # Pattern B test patching (D53): patch BOTH the package re-export
    # AND the internal_router module's bound name. The router imports
    # repos at module-load time via `from ... import ...`, so the
    # package patch alone doesn't reach the call site.
    import app.modules.shorts_auto_product.repositories as repos_pkg
    import app.modules.shorts_auto_product.internal_router as router_module

    for name, fake_factory in [
        ("ProductScanJobRepository", lambda _db: fake_job_repo),
        ("ProductCatalogRepository", lambda _db: fake_catalog_repo),
        ("ProductAppearanceRepository", lambda _db: fake_appearance_repo),
        ("ProductScanDailyCostRepository", lambda _db: fake_cost_repo),
    ]:
        wrapped = MagicMock(side_effect=fake_factory)
        monkeypatch.setattr(repos_pkg, name, wrapped)
        monkeypatch.setattr(router_module, name, wrapped)

    app = FastAPI()
    app.include_router(internal_router)
    fake_db = MagicMock()
    fake_db.commit = AsyncMock()
    app.dependency_overrides[get_db_session] = lambda: fake_db
    app.dependency_overrides[verify_internal_token] = lambda: "test-token"
    return app


def test_complete_scan_order_accepts_appearances_with_catalog_entry_ids(
    monkeypatch,
):
    """**The dual-discriminator regression**: a parent (``mode='scan_order'``,
    ``catalog_entry_id=NULL``) calling ``/complete`` with appearances must
    succeed.

    Pre-fix code branched on ``catalog_entry_id IS NULL`` and would 400
    every parent /complete because it'd demand ``catalog_entries``
    instead.
    """
    parent_id = uuid4()
    catalog_entry_id_a = uuid4()
    catalog_entry_id_b = uuid4()
    job = _job_row(
        job_id=parent_id,
        mode=SCAN_MODE_SCAN_ORDER,
        catalog_entry_id=None,
    )
    job.claimed_by = "test-worker"
    job.org_id = uuid4()

    app = _build_complete_app(
        monkeypatch, job=job, persisted_appearance_count=2,
    )
    client = TestClient(app)
    body = {
        "claimed_by": "test-worker",
        "cost_delta_usd": "0",
        "appearances": [
            {
                "catalog_entry_id": str(catalog_entry_id_a),
                "scene_id": "scene_001",
                "window_start_ms": 1000,
                "window_end_ms": 5000,
                "avg_bbox_area_pct": 0.2,
                "avg_confidence": 0.9,
                "tracker_version": "v1",
            },
            {
                "catalog_entry_id": str(catalog_entry_id_b),
                "scene_id": "scene_002",
                "window_start_ms": 6000,
                "window_end_ms": 10000,
                "avg_bbox_area_pct": 0.3,
                "avg_confidence": 0.85,
                "tracker_version": "v1",
            },
        ],
    }
    resp = client.post(
        f"/internal/products/{parent_id}/complete",
        json=body,
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["persisted_appearances"] == 2


def test_complete_scan_order_rejects_appearance_missing_catalog_entry_id(
    monkeypatch,
):
    """scan_order parents process the whole catalog so each appearance
    MUST carry its own ``catalog_entry_id``. Missing → 400."""
    parent_id = uuid4()
    job = _job_row(
        job_id=parent_id,
        mode=SCAN_MODE_SCAN_ORDER,
        catalog_entry_id=None,
    )
    job.claimed_by = "test-worker"
    job.org_id = uuid4()

    app = _build_complete_app(monkeypatch, job=job)
    client = TestClient(app)
    body = {
        "claimed_by": "test-worker",
        "cost_delta_usd": "0",
        "appearances": [
            {
                # NO catalog_entry_id — should 400
                "scene_id": "scene_001",
                "window_start_ms": 1000,
                "window_end_ms": 5000,
                "avg_bbox_area_pct": 0.2,
                "avg_confidence": 0.9,
                "tracker_version": "v1",
            },
        ],
    }
    resp = client.post(
        f"/internal/products/{parent_id}/complete",
        json=body,
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 400
    assert "catalog_entry_id" in resp.text


def test_complete_scan_order_forces_render_job_id_to_none(monkeypatch):
    """**Q4 codex defense in depth**: even if a buggy worker passes
    ``render_job_id`` in the body for a scan_order parent, the
    persistence layer must force it to NULL.
    """
    parent_id = uuid4()
    catalog_entry_id = uuid4()
    job = _job_row(
        job_id=parent_id,
        mode=SCAN_MODE_SCAN_ORDER,
        catalog_entry_id=None,
    )
    job.claimed_by = "test-worker"
    job.org_id = uuid4()

    app = _build_complete_app(
        monkeypatch, job=job, persisted_appearance_count=1,
    )
    # Capture the call args to complete_tracking so we can assert
    # render_job_id was forced to None.
    import app.modules.shorts_auto_product.repositories as repos_pkg
    fake_factory = repos_pkg.ProductScanJobRepository
    fake_job_repo = fake_factory(MagicMock())

    client = TestClient(app)
    bogus_render_id = uuid4()
    body = {
        "claimed_by": "test-worker",
        "cost_delta_usd": "0",
        "render_job_id": str(bogus_render_id),  # buggy worker; should be ignored
        "appearances": [
            {
                "catalog_entry_id": str(catalog_entry_id),
                "scene_id": "scene_001",
                "window_start_ms": 1000,
                "window_end_ms": 5000,
                "avg_bbox_area_pct": 0.2,
                "avg_confidence": 0.9,
                "tracker_version": "v1",
            },
        ],
    }
    resp = client.post(
        f"/internal/products/{parent_id}/complete",
        json=body,
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200, resp.text
    # complete_tracking must be called with render_job_id=None
    assert fake_job_repo.complete_tracking.await_args.kwargs[
        "render_job_id"
    ] is None


def test_complete_legacy_tracking_path_unchanged(monkeypatch):
    """Backward compat: the deprecated ``enqueue_clip`` flow
    (``mode='enumerate'`` AND ``catalog_entry_id IS NOT NULL``) must
    continue to accept appearances without ``catalog_entry_id`` on the
    payload — the API derives it from the job row. +4wk sunset.
    """
    legacy_job_id = uuid4()
    legacy_catalog_entry_id = uuid4()
    job = _job_row(
        job_id=legacy_job_id,
        mode=SCAN_MODE_ENUMERATE,
        catalog_entry_id=legacy_catalog_entry_id,
    )
    job.claimed_by = "test-worker"
    job.org_id = uuid4()

    app = _build_complete_app(
        monkeypatch, job=job, persisted_appearance_count=1,
    )
    client = TestClient(app)
    body = {
        "claimed_by": "test-worker",
        "cost_delta_usd": "0",
        "render_job_id": str(uuid4()),
        "appearances": [
            {
                # NO catalog_entry_id on payload — derived server-side
                "scene_id": "scene_001",
                "window_start_ms": 1000,
                "window_end_ms": 5000,
                "avg_bbox_area_pct": 0.2,
                "avg_confidence": 0.9,
                "tracker_version": "v1",
            },
        ],
    }
    resp = client.post(
        f"/internal/products/{legacy_job_id}/complete",
        json=body,
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200, resp.text


def test_complete_render_child_rejected_via_complete_path(monkeypatch):
    """``mode='render_child'`` callers must NOT call /complete via
    this path. Rejecting here lets us catch contract drift early.
    """
    child_id = uuid4()
    parent_id = uuid4()
    job = _job_row(
        job_id=child_id,
        mode=SCAN_MODE_RENDER_CHILD,
        catalog_entry_id=None,
        parent_job_id=parent_id,
        shorts_index=1,
    )
    job.claimed_by = "test-worker"
    job.org_id = uuid4()

    app = _build_complete_app(monkeypatch, job=job)
    client = TestClient(app)
    body = {
        "claimed_by": "test-worker",
        "cost_delta_usd": "0",
        "render_job_id": str(uuid4()),
    }
    resp = client.post(
        f"/internal/products/{child_id}/complete",
        json=body,
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 400
    assert "render_child" in resp.text
