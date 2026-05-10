"""Phase 4 PR #2 — scan-order service tests.

Covers the wizard's parent-job orchestration plumbing:

* ``compute_settings_hash`` — canonical-JSON SHA256 (codex Q3).
* ``_validate_scan_order_inputs`` — aggregate-output cap + time-range
  sanity (codex Q5).
* ``ProductScanService.enqueue_scan_order`` — pre-flight gates,
  idempotency via settings_hash, parent-row creation.
* ``ProductScanService.get_scan_order_status`` — aggregate shape
  with rollup counters.
* ``ProductScanService.cancel_scan_order`` — cascading cancel.
* ``ProductScanService.commit_scan_order`` — Phase 6 stub.

NOT in CI allowlist (consistent with the rest of the
test_shorts_auto_product_*.py suite).
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.modules.shorts_auto_product.models import (
    SCAN_MODE_RENDER_CHILD,
    SCAN_MODE_SCAN_ORDER,
    SCAN_STAGE_DONE,
    SCAN_STAGE_FAILED,
    SCAN_STAGE_QUEUED,
)
from app.modules.shorts_auto_product.schemas import ScanOrderCreateRequest
from app.modules.shorts_auto_product.service import (
    ProductScanService,
    _validate_scan_order_inputs,
    compute_settings_hash,
)


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------


def _settings_stub(**overrides):
    """Minimal Settings stub for service construction."""
    s = MagicMock()
    s.auto_shorts_product_v2_enabled = True
    s.auto_shorts_product_v2_rollout_pct = 100
    s.auto_shorts_product_v2_daily_budget_usd = 50.0
    s.auto_shorts_product_v2_max_concurrent_per_org = 3
    s.auto_shorts_product_v2_scan_order_idempotency_seconds = 60
    s.auto_shorts_product_v2_tracker_version = "v1.0"
    s.auto_shorts_product_v2_enumeration_prompt_version = "v1.0"
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _build_service(*, settings=None):
    """Construct a ProductScanService with all repos mocked."""
    svc = ProductScanService(
        session=MagicMock(),
        settings=settings or _settings_stub(),
    )
    svc.session.flush = AsyncMock()
    # get_scan_order_status batches a select on ShortsRenderJob.status
    # since v0.16.1 — the mock needs to await-return a result whose
    # ``.all()`` yields an empty list (no render statuses to surface
    # in unit tests; the assertion-on-children focuses on stage logic).
    _empty_result = MagicMock()
    _empty_result.all = MagicMock(return_value=[])
    svc.session.execute = AsyncMock(return_value=_empty_result)
    svc.catalog_repo = MagicMock()
    svc.catalog_repo.list_active_by_video = AsyncMock(return_value=[])
    svc.appearance_repo = MagicMock()
    svc.job_repo = MagicMock()
    svc.cost_repo = MagicMock()
    svc.cost_repo.get_today_cost = AsyncMock(return_value=Decimal("0"))
    svc.job_repo.count_active_for_org = AsyncMock(return_value=0)
    svc.job_repo.find_recent_scan_order_duplicate = AsyncMock(return_value=None)
    return svc


def _scan_order_body(**overrides):
    defaults = {
        "length_seconds": 60,
        "requested_count": 5,
        "time_range_start_ms": None,
        "time_range_end_ms": None,
        "product_distribution": "single",
        "language": "ko",
        "intent": "commit",
    }
    defaults.update(overrides)
    return ScanOrderCreateRequest(**defaults)


# ======================================================================
# compute_settings_hash — canonical-JSON SHA256
# ======================================================================


def test_settings_hash_is_deterministic():
    """Same inputs → same hash. Output is a 64-char hex digest."""
    args = {
        "video_id": UUID("11111111-1111-1111-1111-111111111111"),
        "user_id": UUID("22222222-2222-2222-2222-222222222222"),
        "length_seconds": 60,
        "requested_count": 5,
        "time_range_start_ms": None,
        "time_range_end_ms": None,
        "product_distribution": "single",
        "language": "ko",
        "intent": "commit",
        "active_catalog_entry_ids": ["aaa", "bbb", "ccc"],
        "tracker_version": "v1.0",
        "enumeration_prompt_version": "v1.0",
    }
    h1 = compute_settings_hash(**args)
    h2 = compute_settings_hash(**args)
    assert h1 == h2
    assert len(h1) == 64
    assert all(c in "0123456789abcdef" for c in h1)


def test_settings_hash_intent_separates_preview_from_commit():
    """Codex Q3: preview and commit MUST produce different hashes
    even with otherwise-identical inputs.
    """
    args = {
        "video_id": uuid4(),
        "user_id": uuid4(),
        "length_seconds": 60,
        "requested_count": 5,
        "time_range_start_ms": None,
        "time_range_end_ms": None,
        "product_distribution": "single",
        "language": "ko",
        "active_catalog_entry_ids": [],
        "tracker_version": "v1.0",
        "enumeration_prompt_version": "v1.0",
    }
    preview_hash = compute_settings_hash(intent="preview", **args)
    commit_hash = compute_settings_hash(intent="commit", **args)
    assert preview_hash != commit_hash


def test_settings_hash_catalog_set_changes_hash():
    """Rescan that produces new catalog entries must change the hash
    (the catalog set is the version signal — codex confirmed this
    avoids needing a separate catalog_version column).
    """
    base = {
        "video_id": uuid4(),
        "user_id": uuid4(),
        "length_seconds": 60,
        "requested_count": 5,
        "time_range_start_ms": None,
        "time_range_end_ms": None,
        "product_distribution": "single",
        "language": "ko",
        "intent": "commit",
        "tracker_version": "v1.0",
        "enumeration_prompt_version": "v1.0",
    }
    h_a = compute_settings_hash(active_catalog_entry_ids=["e1", "e2"], **base)
    h_b = compute_settings_hash(active_catalog_entry_ids=["e1", "e2", "e3"], **base)
    assert h_a != h_b


def test_settings_hash_tracker_version_changes_hash():
    """Codex Q3: model bumps invalidate dedupe so re-running after
    a deploy gets fresh output instead of stale cached results.
    """
    base = {
        "video_id": uuid4(),
        "user_id": uuid4(),
        "length_seconds": 60,
        "requested_count": 5,
        "time_range_start_ms": None,
        "time_range_end_ms": None,
        "product_distribution": "single",
        "language": "ko",
        "intent": "commit",
        "active_catalog_entry_ids": [],
        "enumeration_prompt_version": "v1.0",
    }
    h_old = compute_settings_hash(tracker_version="v1.0", **base)
    h_new = compute_settings_hash(tracker_version="v2.0", **base)
    assert h_old != h_new


def test_settings_hash_canonical_json_is_key_order_insensitive():
    """Canonical JSON sorts keys, so dict ordering at the call site
    must not affect the hash. Verified by inspecting that the
    function is deterministic across multiple invocations with the
    same kwargs (Python dict order is insertion-sensitive in 3.7+).
    """
    args_1 = {
        "video_id": uuid4(),
        "user_id": uuid4(),
        "length_seconds": 60,
        "requested_count": 5,
        "time_range_start_ms": None,
        "time_range_end_ms": None,
        "product_distribution": "single",
        "language": "ko",
        "intent": "commit",
        "active_catalog_entry_ids": [],
        "tracker_version": "v1.0",
        "enumeration_prompt_version": "v1.0",
    }
    h1 = compute_settings_hash(**args_1)
    # Reconstruct with reversed kwarg order
    args_2 = dict(reversed(list(args_1.items())))
    h2 = compute_settings_hash(**args_2)
    assert h1 == h2


def test_settings_hash_omits_selected_entry_when_none():
    """Backward compat: scan orders submitted before the product-select
    step shipped (or with the field absent) must hash IDENTICALLY to
    the same call without the parameter, so live idempotency keys
    don't churn during deploy."""
    base = {
        "video_id": uuid4(),
        "user_id": uuid4(),
        "length_seconds": 60,
        "requested_count": 5,
        "time_range_start_ms": None,
        "time_range_end_ms": None,
        "product_distribution": "single",
        "language": "ko",
        "intent": "commit",
        "active_catalog_entry_ids": ["aaa"],
        "tracker_version": "v1.0",
        "enumeration_prompt_version": "v1.0",
    }
    h_no_kwarg = compute_settings_hash(**base)
    h_explicit_none = compute_settings_hash(selected_catalog_entry_id=None, **base)
    assert h_no_kwarg == h_explicit_none


def test_settings_hash_changes_when_user_picks_a_product():
    """Picking a product semantically narrows the job — must produce a
    distinct dedupe key from the same wizard inputs without a pick."""
    base = {
        "video_id": uuid4(),
        "user_id": uuid4(),
        "length_seconds": 60,
        "requested_count": 5,
        "time_range_start_ms": None,
        "time_range_end_ms": None,
        "product_distribution": "single",
        "language": "ko",
        "intent": "commit",
        "active_catalog_entry_ids": ["aaa", "bbb"],
        "tracker_version": "v1.0",
        "enumeration_prompt_version": "v1.0",
    }
    h_unpicked = compute_settings_hash(**base)
    h_picked_a = compute_settings_hash(selected_catalog_entry_id="aaa", **base)
    h_picked_b = compute_settings_hash(selected_catalog_entry_id="bbb", **base)
    # Three distinct intents → three distinct hashes.
    assert len({h_unpicked, h_picked_a, h_picked_b}) == 3


# ======================================================================
# _validate_scan_order_inputs — codex Q5 aggregate cap + time range
# ======================================================================


def test_validate_aggregate_cap_under_limit_passes():
    """count=15 × length=120 = 1800 — exactly at the cap, accepted."""
    body = _scan_order_body(requested_count=15, length_seconds=120)
    _validate_scan_order_inputs(body=body)


def test_validate_aggregate_cap_over_limit_422():
    """count=20 × length=120 = 2400 → 422 with clear message."""
    body = _scan_order_body(requested_count=20, length_seconds=120)
    with pytest.raises(HTTPException) as exc:
        _validate_scan_order_inputs(body=body)
    assert exc.value.status_code == 422
    assert "1800" in str(exc.value.detail)


def test_validate_time_range_partial_422():
    """Setting only start (not end) — 422."""
    body = _scan_order_body(time_range_start_ms=1000)
    with pytest.raises(HTTPException) as exc:
        _validate_scan_order_inputs(body=body)
    assert exc.value.status_code == 422


def test_validate_time_range_inverted_422():
    """end <= start — 422."""
    body = _scan_order_body(
        time_range_start_ms=5000,
        time_range_end_ms=2000,
        requested_count=2,  # so the per-short check doesn't fire first
    )
    with pytest.raises(HTTPException) as exc:
        _validate_scan_order_inputs(body=body)
    assert exc.value.status_code == 422


def test_validate_time_range_too_short_per_short_422():
    """count=10 shorts × 60s each = 600s required source.
    Range = 300s → 30s/short → 422.
    """
    body = _scan_order_body(
        length_seconds=60,
        requested_count=10,
        time_range_start_ms=0,
        time_range_end_ms=300_000,
    )
    with pytest.raises(HTTPException) as exc:
        _validate_scan_order_inputs(body=body)
    assert exc.value.status_code == 422
    assert "source" in str(exc.value.detail)


def test_validate_time_range_sufficient_passes():
    """count=5 × 60s each = 300s required.
    Range = 600s → 120s/short → passes.
    """
    body = _scan_order_body(
        length_seconds=60,
        requested_count=5,
        time_range_start_ms=0,
        time_range_end_ms=600_000,
    )
    _validate_scan_order_inputs(body=body)


# ======================================================================
# ProductScanService.enqueue_scan_order
# ======================================================================


@pytest.mark.asyncio
async def test_enqueue_scan_order_happy_path_creates_parent():
    """End-to-end: validation passes → settings_hash computed →
    no dedupe match → parent row created → response returned."""
    svc = _build_service()
    org_id = uuid4()
    video_id = uuid4()
    user_id = uuid4()

    parent = MagicMock()
    parent.id = uuid4()
    svc.job_repo.create_scan_order_parent = AsyncMock(return_value=parent)

    body = _scan_order_body(
        length_seconds=60, requested_count=5,
        product_distribution="single", language="ko", intent="commit",
    )
    resp = await svc.enqueue_scan_order(
        org_id=org_id, video_id=video_id, user_id=user_id, body=body,
    )
    assert resp.parent_job_id == parent.id
    assert resp.deduped is False
    # Verify settings_hash was passed and is a 64-char hex string.
    call_kwargs = svc.job_repo.create_scan_order_parent.await_args.kwargs
    assert len(call_kwargs["settings_hash"]) == 64


@pytest.mark.asyncio
async def test_enqueue_scan_order_dedupes_within_window():
    """Existing parent with matching settings_hash → return existing
    job_id with deduped=True; no new row created.
    """
    svc = _build_service()
    org_id = uuid4()
    user_id = uuid4()
    existing_parent = MagicMock()
    existing_parent.id = uuid4()
    svc.job_repo.find_recent_scan_order_duplicate = AsyncMock(
        return_value=existing_parent,
    )
    svc.job_repo.create_scan_order_parent = AsyncMock()

    resp = await svc.enqueue_scan_order(
        org_id=org_id, video_id=uuid4(), user_id=user_id, body=_scan_order_body(),
    )
    assert resp.deduped is True
    assert resp.parent_job_id == existing_parent.id
    svc.job_repo.create_scan_order_parent.assert_not_awaited()


@pytest.mark.asyncio
async def test_enqueue_scan_order_aggregate_cap_422():
    svc = _build_service()
    body = _scan_order_body(requested_count=20, length_seconds=120)
    with pytest.raises(HTTPException) as exc:
        await svc.enqueue_scan_order(
            org_id=uuid4(), video_id=uuid4(), user_id=uuid4(), body=body,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_enqueue_scan_order_budget_402():
    settings = _settings_stub(auto_shorts_product_v2_daily_budget_usd=10.0)
    svc = _build_service(settings=settings)
    svc.cost_repo.get_today_cost = AsyncMock(return_value=Decimal("10.5"))

    with pytest.raises(HTTPException) as exc:
        await svc.enqueue_scan_order(
            org_id=uuid4(), video_id=uuid4(), user_id=uuid4(), body=_scan_order_body(),
        )
    assert exc.value.status_code == 402


@pytest.mark.asyncio
async def test_enqueue_scan_order_concurrency_429():
    svc = _build_service()
    svc.job_repo.count_active_for_org = AsyncMock(return_value=3)

    with pytest.raises(HTTPException) as exc:
        await svc.enqueue_scan_order(
            org_id=uuid4(), video_id=uuid4(), user_id=uuid4(), body=_scan_order_body(),
        )
    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_enqueue_scan_order_disabled_404():
    settings = _settings_stub(auto_shorts_product_v2_enabled=False)
    svc = _build_service(settings=settings)

    with pytest.raises(HTTPException) as exc:
        await svc.enqueue_scan_order(
            org_id=uuid4(), video_id=uuid4(), user_id=uuid4(), body=_scan_order_body(),
        )
    assert exc.value.status_code == 404


# ======================================================================
# ProductScanService.get_scan_order_status
# ======================================================================


@pytest.mark.asyncio
async def test_get_scan_order_status_aggregates_children():
    """Parent + 3 children (1 done, 1 failed, 1 in-flight) → response
    carries rollup counters for the wizard's progress UI.
    """
    svc = _build_service()
    parent_id = uuid4()
    org_id = uuid4()

    parent = MagicMock()
    parent.id = parent_id
    parent.mode = SCAN_MODE_SCAN_ORDER
    parent.catalog_entry_id = None
    parent.parent_job_id = None
    parent.shorts_index = None
    parent.render_job_id = None
    parent.stage = "fanned_out"
    parent.progress_pct = 100
    parent.progress_label = None
    parent.completed_at = None
    parent.failed_at = None
    parent.cancelled_at = None
    parent.error_code = None
    parent.error_message = None
    parent.cost_usd_estimate = Decimal("0.5")

    def _child(idx, *, stage, completed_at=None, failed_at=None):
        c = MagicMock()
        c.id = uuid4()
        c.mode = SCAN_MODE_RENDER_CHILD
        c.catalog_entry_id = None
        c.parent_job_id = parent_id
        c.shorts_index = idx
        c.render_job_id = uuid4() if completed_at else None
        c.stage = stage
        c.progress_pct = 100 if completed_at else (50 if not failed_at else 0)
        c.progress_label = None
        c.completed_at = completed_at
        c.failed_at = failed_at
        c.cancelled_at = None
        c.error_code = None
        c.error_message = None
        c.cost_usd_estimate = Decimal("0")
        return c

    from datetime import datetime, timezone
    children = [
        _child(1, stage=SCAN_STAGE_DONE, completed_at=datetime.now(timezone.utc)),
        _child(2, stage=SCAN_STAGE_FAILED, failed_at=datetime.now(timezone.utc)),
        _child(3, stage="rendering"),
    ]
    svc.job_repo.get_scan_order_with_children = AsyncMock(
        return_value=(parent, children),
    )

    resp = await svc.get_scan_order_status(
        org_id=org_id, parent_job_id=parent_id,
    )
    assert resp.parent.kind == "scan_order"
    assert resp.parent.render_job_id is None  # Q4 invariant
    assert len(resp.children) == 3
    assert resp.children_total == 3
    assert resp.children_complete == 1
    assert resp.children_failed == 1


@pytest.mark.asyncio
async def test_get_scan_order_status_404_when_missing():
    svc = _build_service()
    svc.job_repo.get_scan_order_with_children = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc:
        await svc.get_scan_order_status(
            org_id=uuid4(), parent_job_id=uuid4(),
        )
    assert exc.value.status_code == 404


# ======================================================================
# ProductScanService.cancel_scan_order
# ======================================================================


@pytest.mark.asyncio
async def test_cancel_scan_order_cascades():
    svc = _build_service()
    parent = MagicMock()
    parent.mode = SCAN_MODE_SCAN_ORDER
    svc.job_repo.get = AsyncMock(return_value=parent)
    # 1 parent + 3 children all transitioned
    svc.job_repo.cancel_scan_order = AsyncMock(return_value=4)

    await svc.cancel_scan_order(org_id=uuid4(), parent_job_id=uuid4())
    svc.job_repo.cancel_scan_order.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_scan_order_404_when_missing():
    svc = _build_service()
    svc.job_repo.get = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc:
        await svc.cancel_scan_order(org_id=uuid4(), parent_job_id=uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_cancel_scan_order_404_when_already_terminal():
    svc = _build_service()
    parent = MagicMock()
    parent.mode = SCAN_MODE_SCAN_ORDER
    svc.job_repo.get = AsyncMock(return_value=parent)
    svc.job_repo.cancel_scan_order = AsyncMock(return_value=0)  # nothing to cancel

    with pytest.raises(HTTPException) as exc:
        await svc.cancel_scan_order(org_id=uuid4(), parent_job_id=uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_cancel_scan_order_404_when_wrong_mode():
    """Targeting a non-scan_order job for cancel via this endpoint
    must 404 (legacy enumerate / clip jobs use the existing
    /jobs/{id}/cancel endpoint)."""
    svc = _build_service()
    parent = MagicMock()
    parent.mode = "enumerate"  # not scan_order
    svc.job_repo.get = AsyncMock(return_value=parent)

    with pytest.raises(HTTPException) as exc:
        await svc.cancel_scan_order(org_id=uuid4(), parent_job_id=uuid4())
    assert exc.value.status_code == 404


# ======================================================================
# ProductScanService.commit_scan_order — Phase 6 stub
# ======================================================================


@pytest.mark.asyncio
async def test_commit_scan_order_returns_501():
    svc = _build_service()
    with pytest.raises(HTTPException) as exc:
        await svc.commit_scan_order(
            org_id=uuid4(),
            parent_job_id=uuid4(),
            selected_window_ids=None,
        )
    assert exc.value.status_code == 501
    assert "Phase 6" in exc.value.detail


# ======================================================================
# PR 1 of multi-product wizard — single-pick propagation to children
# ======================================================================
#
# The pre-PR-1 behavior: parent.catalog_entry_id was set when the user
# picked a product, but the api-process runner ignored it (latent bug).
# PR 1 propagates the pick to every child at fan-out time so the runner
# honors it. These tests verify the propagation in the STT-mode service
# path; the actual runner-side use is tested in
# ``test_shorts_auto_product_child_runner.py``.
#
# Plan: ``.claude/plans/wizard-multi-product-select.md`` (PR 1 of 3).


def _stt_settings(**overrides):
    """Settings stub configured for the STT inline fan-out path."""
    return _settings_stub(
        auto_shorts_product_v2_track_mode="stt",
        auto_shorts_product_v2_publish_scan_order_enabled=False,
        **overrides,
    )


def _stt_service():
    """Service with STT-mode settings + a fake parent factory wired so
    enqueue_scan_order's STT branch fans out without raising."""
    svc = _build_service(settings=_stt_settings())
    fake_parent = MagicMock(id=uuid4(), requested_count=5)
    svc.job_repo.create_scan_order_parent = AsyncMock(return_value=fake_parent)
    svc.job_repo.create_render_children = AsyncMock(return_value=[])
    svc.job_repo.transition_parent_to_fanned_out_unclaimed = AsyncMock()
    # Wizard's product-select prerequisite: catalog must contain the picked entry.
    # Mocked at body-validation time via catalog_repo.get returning a non-rejected entry.
    svc.catalog_repo.get = AsyncMock(return_value=MagicMock(
        video_id=None,  # set per-test if a body has video_id check
        rejected_at=None,
    ))
    return svc


@pytest.mark.asyncio
async def test_stt_fanout_no_pick_passes_no_assignments():
    """Whole-catalog mode (legacy default): body.catalog_entry_id=None
    → ``create_render_children`` is called WITHOUT
    ``catalog_entry_assignments`` (or with None). Children stay NULL,
    runner falls back to picker round-robin (preserved behavior)."""
    svc = _stt_service()
    body = _scan_order_body(catalog_entry_id=None)

    await svc.enqueue_scan_order(
        org_id=uuid4(), video_id=uuid4(), user_id=uuid4(), body=body,
    )

    svc.job_repo.create_render_children.assert_awaited_once()
    call_kwargs = svc.job_repo.create_render_children.await_args.kwargs
    assert call_kwargs.get("catalog_entry_assignments") is None, (
        f"Expected no assignments for whole-catalog mode, got: {call_kwargs}"
    )


@pytest.mark.asyncio
async def test_stt_fanout_single_pick_propagates_to_every_child():
    """Single-pick wizard: body.catalog_entry_id=X, requested_count=5
    → ``catalog_entry_assignments=[X, X, X, X, X]`` so each child
    carries the pick. Fixes the latent single-pick bug — without this,
    children get NULL and the runner round-robins across the whole
    catalog."""
    svc = _stt_service()
    picked = uuid4()
    video_id = uuid4()
    # catalog_repo.get must return a row that matches video_id and is not rejected.
    svc.catalog_repo.get = AsyncMock(return_value=MagicMock(
        video_id=video_id, rejected_at=None,
    ))
    body = _scan_order_body(catalog_entry_id=picked, requested_count=5)

    await svc.enqueue_scan_order(
        org_id=uuid4(), video_id=video_id, user_id=uuid4(), body=body,
    )

    svc.job_repo.create_render_children.assert_awaited_once()
    call_kwargs = svc.job_repo.create_render_children.await_args.kwargs
    assignments = call_kwargs.get("catalog_entry_assignments")
    assert assignments == [picked] * 5, (
        f"Expected uniform [X]*5 assignment for single-pick body, got: {assignments}"
    )


@pytest.mark.asyncio
async def test_stt_fanout_single_pick_count_matches_requested_count():
    """Edge: requested_count=1 → single-element list of one. Confirms
    no off-by-one in the propagation."""
    svc = _stt_service()
    picked = uuid4()
    video_id = uuid4()
    svc.catalog_repo.get = AsyncMock(return_value=MagicMock(
        video_id=video_id, rejected_at=None,
    ))
    body = _scan_order_body(catalog_entry_id=picked, requested_count=1)

    await svc.enqueue_scan_order(
        org_id=uuid4(), video_id=video_id, user_id=uuid4(), body=body,
    )

    call_kwargs = svc.job_repo.create_render_children.await_args.kwargs
    assert call_kwargs.get("catalog_entry_assignments") == [picked]
