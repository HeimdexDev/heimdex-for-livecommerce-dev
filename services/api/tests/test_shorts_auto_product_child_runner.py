"""Phase 4 PR #4 — child runner tests.

Covers the in-API-process child runner that picks up queued
``mode='render_child'`` rows produced by the parent fan-out hook.

Tests are unit-scope (no real Postgres). The DB-atomic claim race is
simulated by mocking the repo's ``claim`` method to return None on
the losing call — sufficient to verify the runner's behavior since
the actual race resolution is Postgres's atomic UPDATE, not anything
the runner itself does.

NOT in CI allowlist (consistent with the rest of the
test_shorts_auto_product_*.py suite).
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.modules.shorts_auto_product.children.runner import ChildRunner


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------


def _settings_stub(
    *,
    max_concurrency: int = 4,
    poll_seconds: float = 0.05,
    lease_seconds: int = 300,
    enabled: bool = True,
):
    s = MagicMock()
    s.auto_shorts_product_v2_child_runner_max_concurrency = max_concurrency
    s.auto_shorts_product_v2_child_runner_poll_seconds = poll_seconds
    s.auto_shorts_product_v2_child_lease_seconds = lease_seconds
    s.auto_shorts_product_v2_child_runner_enabled = enabled
    return s


def _mock_session_factory(repo_factory):
    """Build a session factory that yields a MagicMock session and
    arranges for ``ProductScanJobRepository(session)`` to return the
    fake repo built by ``repo_factory``.

    Uses Pattern B test patching (D53) — the runner constructs
    ``ProductScanJobRepository(session)`` directly, so we monkeypatch
    the class to return the fake.
    """

    @asynccontextmanager
    async def factory():
        session = MagicMock()
        session.commit = AsyncMock()
        yield session

    return factory


def _patch_repo(monkeypatch, fake_repo):
    """Patch ``ProductScanJobRepository`` to return ``fake_repo``
    regardless of the session it's constructed with."""
    import app.modules.shorts_auto_product.children.runner as runner_module

    monkeypatch.setattr(
        runner_module,
        "ProductScanJobRepository",
        MagicMock(return_value=fake_repo),
    )


def _build_runner(monkeypatch, *, settings=None, fake_repo=None,
                  process_child_fn=None, instance_id="test-replica"):
    """Construct a ChildRunner with all deps mocked."""
    settings = settings or _settings_stub()
    fake_repo = fake_repo or MagicMock()
    fake_repo.find_queued_render_children = AsyncMock(return_value=[])
    fake_repo.claim = AsyncMock(return_value=MagicMock())
    fake_repo.complete_tracking = AsyncMock(return_value=MagicMock())
    fake_repo.fail = AsyncMock()
    _patch_repo(monkeypatch, fake_repo)
    return ChildRunner(
        settings=settings,
        session_factory=_mock_session_factory(fake_repo),
        scene_search_client=MagicMock(),  # PR #6: not exercised by these tests
        instance_id=instance_id,
        process_child_fn=process_child_fn,
    ), fake_repo


# ======================================================================
# claimed_by identifier
# ======================================================================


def test_claimed_by_includes_instance_id(monkeypatch):
    runner, _ = _build_runner(monkeypatch, instance_id="api-replica-7")
    assert runner.claimed_by == "api-child-api-replica-7"


def test_default_instance_id_uses_hostname(monkeypatch):
    """If HOSTNAME is set (every container runtime sets this), the
    runner uses it. Otherwise falls back to socket.gethostname()."""
    monkeypatch.setenv("HOSTNAME", "ec2-host-42")
    from app.modules.shorts_auto_product.children.runner import _default_instance_id

    assert _default_instance_id() == "ec2-host-42"


# ======================================================================
# Processing flow (PR #6): claim → real flow OR no-render fallback
# ======================================================================
#
# The PR #4 stub ("claim → /complete with render_job_id=None") was
# replaced in PR #6 with a real picker + render-service flow. The
# tests below cover the orchestration spine; the no-render fallback
# path is the easiest one to drive end-to-end without standing up
# real catalog / appearance / render fixtures.


@pytest.mark.asyncio
async def test_process_child_payload_no_render_path_claims_then_completes(monkeypatch):
    """No-render fallback path: when the runner can't produce a
    render (no catalog, no appearances, picker returns nothing), it
    still claims the child and completes it with ``render_job_id=None``
    so the wizard UI shows "no render produced for this short"
    rather than leaving the child in 'assembling' until lease
    expiry. Forced here by patching ``_load_child_context`` to
    return None (``no_catalog_or_parent`` branch)."""
    runner, fake_repo = _build_runner(monkeypatch)
    child_id = uuid4()
    fake_repo.claim = AsyncMock(return_value=MagicMock())  # claim wins
    fake_repo.complete_tracking = AsyncMock(return_value=MagicMock())

    # Force the no-render branch — simulates "parent is gone" /
    # "video has no active catalog entries". Either is a legitimate
    # terminal state that the runner handles by completing the
    # child with no render rather than failing it.
    monkeypatch.setattr(
        runner, "_load_child_context", AsyncMock(return_value=None),
    )

    await runner._process_child_payload(child_id)

    fake_repo.claim.assert_awaited_once()
    claim_kwargs = fake_repo.claim.await_args.kwargs
    assert claim_kwargs["job_id"] == child_id
    assert claim_kwargs["claimed_by"] == "api-child-test-replica"
    assert claim_kwargs["next_stage"] == "assembling"

    fake_repo.complete_tracking.assert_awaited_once()
    complete_kwargs = fake_repo.complete_tracking.await_args.kwargs
    assert complete_kwargs["job_id"] == child_id
    assert complete_kwargs["claimed_by"] == "api-child-test-replica"
    assert complete_kwargs["render_job_id"] is None


@pytest.mark.asyncio
async def test_process_child_payload_skips_when_already_claimed(monkeypatch):
    """Race-loser path: claim returns None (another replica already
    claimed) → no /complete call, silent no-op."""
    runner, fake_repo = _build_runner(monkeypatch)
    fake_repo.claim = AsyncMock(return_value=None)  # claim lost the race

    await runner._process_child_payload(uuid4())

    fake_repo.claim.assert_awaited_once()
    fake_repo.complete_tracking.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_child_payload_no_render_path_handles_lease_loss(monkeypatch):
    """Lease lost between claim and complete on the no-render path
    (e.g. cancel cascade ran mid-process) → warn but don't crash.
    The row is already in its terminal state from the cancel —
    nothing for us to do."""
    runner, fake_repo = _build_runner(monkeypatch)
    fake_repo.claim = AsyncMock(return_value=MagicMock())
    fake_repo.complete_tracking = AsyncMock(return_value=None)  # lease lost
    monkeypatch.setattr(
        runner, "_load_child_context", AsyncMock(return_value=None),
    )

    # Should not raise; quietly returns.
    await runner._process_child_payload(uuid4())

    fake_repo.complete_tracking.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_one_child_marks_failed_on_exception(monkeypatch):
    """If the processing step raises, the runner catches the exception
    and best-effort marks the child as failed. Without this, a single
    bad child would leave the row in 'assembling' until the lease
    expires (5 min) and another replica retries — wasted cycles.
    """
    runner, fake_repo = _build_runner(monkeypatch)
    child_id = uuid4()

    # Inject a process_child_fn that always raises.
    async def failing_process(_id):
        raise ValueError("bang")

    runner._process_child_fn = failing_process

    await runner._run_one_child(child_id)

    # _mark_child_failed should have been called and called repo.fail
    fake_repo.fail.assert_awaited_once()
    fail_kwargs = fake_repo.fail.await_args.kwargs
    assert fail_kwargs["job_id"] == child_id
    assert fail_kwargs["error_code"] == "internal_error"
    assert "crashed" in fail_kwargs["error_message"]


# ======================================================================
# Multi-replica race simulation
# ======================================================================


@pytest.mark.asyncio
async def test_two_replicas_race_only_one_wins(monkeypatch):
    """Simulate two replicas seeing the same queued child id. The
    DB-atomic claim only succeeds once; the second replica's claim
    returns None and silently no-ops.

    This isn't a real race test (no concurrent DB) — it's a behavior
    contract test: prove the runner correctly handles ``claim ==
    None`` as the lost-race signal.
    """
    child_id = uuid4()

    # Replica A: claim succeeds
    runner_a, repo_a = _build_runner(
        monkeypatch, instance_id="replica-A",
    )
    repo_a.claim = AsyncMock(return_value=MagicMock())
    repo_a.complete_tracking = AsyncMock(return_value=MagicMock())
    # PR #6: post-claim, the runner's real flow walks
    # _load_child_context → catalog/appearances → render service.
    # This test only cares about the claim race contract, so force
    # the no-render branch so we exit at complete_tracking without
    # needing to mock the entire real-flow chain.
    monkeypatch.setattr(
        runner_a, "_load_child_context", AsyncMock(return_value=None),
    )

    # Replica B: claim loses
    repo_b = MagicMock()
    repo_b.find_queued_render_children = AsyncMock(return_value=[])
    repo_b.claim = AsyncMock(return_value=None)
    repo_b.complete_tracking = AsyncMock()
    repo_b.fail = AsyncMock()
    runner_b = ChildRunner(
        settings=_settings_stub(),
        session_factory=_mock_session_factory(repo_b),
        scene_search_client=MagicMock(),
        instance_id="replica-B",
    )

    # Each replica processes the same child_id (this is what would
    # happen if both polls returned overlapping candidates).
    # Patch repo into runner_b too — _build_runner already patched
    # for runner_a, so we need to overwrite with repo_b.
    import app.modules.shorts_auto_product.children.runner as runner_module
    original_repo_class = runner_module.ProductScanJobRepository

    # Use a side_effect to alternate between repos based on call order
    # since both runners share the patched class. Simpler: process
    # serially with explicit class swaps.
    monkeypatch.setattr(
        runner_module,
        "ProductScanJobRepository",
        MagicMock(return_value=repo_a),
    )
    await runner_a._process_child_payload(child_id)

    monkeypatch.setattr(
        runner_module,
        "ProductScanJobRepository",
        MagicMock(return_value=repo_b),
    )
    await runner_b._process_child_payload(child_id)

    # Replica A: claimed, completed.
    repo_a.complete_tracking.assert_awaited_once()
    # Replica B: claim returned None, no /complete call.
    repo_b.complete_tracking.assert_not_awaited()


# ======================================================================
# Bounded concurrency
# ======================================================================


@pytest.mark.asyncio
async def test_bounded_concurrency_caps_inflight(monkeypatch):
    """Dispatch 10 children with max_concurrency=2; at most 2 should
    be in-flight at any time. Verified by counting concurrent
    process_child_fn invocations.
    """
    settings = _settings_stub(max_concurrency=2)
    inflight_now = 0
    max_seen = 0

    async def slow_process(_child_id):
        nonlocal inflight_now, max_seen
        inflight_now += 1
        max_seen = max(max_seen, inflight_now)
        try:
            await asyncio.sleep(0.05)
        finally:
            inflight_now -= 1

    runner, _ = _build_runner(
        monkeypatch, settings=settings, process_child_fn=slow_process,
    )

    # Fire 10 children directly via _run_one_child.
    tasks = [
        asyncio.create_task(runner._run_one_child(uuid4()))
        for _ in range(10)
    ]
    await asyncio.gather(*tasks)

    assert max_seen <= 2, (
        f"max_concurrency=2 violated; saw {max_seen} concurrent processes"
    )


# ======================================================================
# Disabled flag
# ======================================================================


@pytest.mark.asyncio
async def test_runner_disabled_exits_loop_immediately(monkeypatch):
    """When ``auto_shorts_product_v2_child_runner_enabled`` is False,
    the loop logs and returns without polling. Lets operators
    suspend wizard fan-out without redeploying."""
    settings = _settings_stub(enabled=False)
    runner, fake_repo = _build_runner(monkeypatch, settings=settings)

    runner.start()
    await asyncio.wait_for(runner._task, timeout=1.0)

    # find_queued_render_children should never have been called.
    fake_repo.find_queued_render_children.assert_not_awaited()


# ======================================================================
# Lifecycle: start / stop drain
# ======================================================================


@pytest.mark.asyncio
async def test_start_then_stop_drains_inflight(monkeypatch):
    """In-flight children at shutdown finish their current iteration
    before the runner returns.
    """
    settings = _settings_stub(poll_seconds=0.01)
    completed_ids: list[UUID] = []

    async def slow_process(child_id):
        await asyncio.sleep(0.05)
        completed_ids.append(child_id)

    runner, fake_repo = _build_runner(
        monkeypatch, settings=settings, process_child_fn=slow_process,
    )
    queued = [uuid4(), uuid4(), uuid4()]
    # First poll returns 3 candidates; subsequent polls return [].
    fake_repo.find_queued_render_children = AsyncMock(
        side_effect=[queued, [], [], [], []],
    )

    runner.start()
    # Give the runner time to dispatch all 3 children.
    await asyncio.sleep(0.05)
    # Stop and drain. Drain timeout > slow_process duration so all
    # 3 children complete cleanly.
    await runner.stop(drain_timeout_seconds=2.0)

    assert len(completed_ids) == 3
    # Tasks should all be cleaned up from the inflight set.
    assert len(runner._inflight) == 0


@pytest.mark.asyncio
async def test_stop_is_idempotent(monkeypatch):
    """Calling stop twice is safe."""
    runner, _ = _build_runner(monkeypatch)
    runner.start()
    await asyncio.sleep(0.01)
    await runner.stop(drain_timeout_seconds=0.5)
    await runner.stop(drain_timeout_seconds=0.5)  # second call no-ops
