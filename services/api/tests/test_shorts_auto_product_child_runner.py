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
    eager_promotion_enabled: bool = True,
):
    s = MagicMock()
    s.auto_shorts_product_v2_child_runner_max_concurrency = max_concurrency
    s.auto_shorts_product_v2_child_runner_poll_seconds = poll_seconds
    s.auto_shorts_product_v2_child_lease_seconds = lease_seconds
    s.auto_shorts_product_v2_child_runner_enabled = enabled
    # PR 2: eager parent promotion flag. Defaults true to match the
    # config default and let existing tests run the new code path
    # transparently (the helper is no-op'd via AsyncMocks below).
    s.auto_shorts_product_v2_eager_parent_promotion_enabled = eager_promotion_enabled
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
    from datetime import datetime, timezone

    settings = settings or _settings_stub()
    fake_repo = fake_repo or MagicMock()
    fake_repo.find_queued_render_children = AsyncMock(return_value=[])
    # PR 3: the runner's _poll_and_dispatch branches on the self-heal
    # flag and calls find_claimable_render_children when on. Mock
    # both so existing tests don't depend on which branch runs.
    fake_repo.find_claimable_render_children = AsyncMock(return_value=[])

    # PR 3: the runner reads claimed.started_at and claimed.claimed_at
    # to detect re-claim of expired lease (started_at < claimed_at).
    # Provide real datetime values so the comparison doesn't raise on
    # MagicMock (Python 3.11 disallows ordered comparison between
    # bare MagicMocks). Equal values = "fresh claim" — suppresses the
    # re-claim warning for tests that don't care.
    _now = datetime.now(timezone.utc)
    _claimed_default = MagicMock()
    _claimed_default.started_at = _now
    _claimed_default.claimed_at = _now
    fake_repo.claim = AsyncMock(return_value=_claimed_default)
    fake_repo.heartbeat = AsyncMock(return_value=MagicMock())

    fake_repo.complete_tracking = AsyncMock(return_value=MagicMock())
    fake_repo.fail = AsyncMock()
    # PR 2: the runner calls _try_promote_parent_for_child after
    # every child terminal transition. The helper opens a session and
    # calls these two repo methods; mock both so existing tests don't
    # trip on awaiting MagicMocks. Tests that care about promotion
    # behaviour override these per-case.
    fake_repo.get_internal = AsyncMock(return_value=None)
    fake_repo.try_promote_parent_if_all_children_terminal = AsyncMock(
        return_value=None,
    )
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
async def test_child_lease_heartbeat_extends_current_claim(monkeypatch):
    """The runner-owned heartbeat must renew a child lease with the
    same claimed_by token used for the original claim. A stale runner
    gets ``None`` back from the repo and treats the lease as lost.
    """
    settings = _settings_stub(lease_seconds=123)
    runner, fake_repo = _build_runner(monkeypatch, settings=settings)
    child_id = uuid4()

    ok = await runner._heartbeat_child_lease(
        child_id=child_id,
        stage="rendering",
        progress_pct=75,
        progress_label="rendering",
    )

    assert ok is True
    fake_repo.heartbeat.assert_awaited_once()
    kwargs = fake_repo.heartbeat.await_args.kwargs
    assert kwargs["job_id"] == child_id
    assert kwargs["claimed_by"] == "api-child-test-replica"
    assert kwargs["stage"] == "rendering"
    assert kwargs["progress_pct"] == 75
    assert kwargs["progress_label"] == "rendering"
    assert kwargs["lease_seconds"] == 123


@pytest.mark.asyncio
async def test_render_enqueue_skipped_when_child_lease_lost(monkeypatch):
    """Before creating a ShortsRenderJob the runner performs a fresh
    heartbeat. If that guarded write returns None, another replica or
    cancellation owns the row, so this runner must not enqueue a render.
    """
    runner, _ = _build_runner(monkeypatch)
    child_id = uuid4()
    catalog_id = uuid4()
    child = MagicMock(
        id=child_id,
        catalog_entry_id=catalog_id,
        shorts_index=1,
    )
    parent = MagicMock(
        id=uuid4(),
        org_id=uuid4(),
        video_id=uuid4(),
        product_distribution=None,
        length_seconds=60,
        duration_preset_sec=None,
        requested_by_user_id=uuid4(),
    )
    monkeypatch.setattr(
        runner,
        "_load_child_context",
        AsyncMock(return_value=(child, parent, {catalog_id: "Product"}, {catalog_id: ["Product"]})),
    )

    appearance = MagicMock()
    appearance.scene_id = "gd_video_1_scene_001"
    appearance.window_start_ms = 0
    appearance.window_end_ms = 5000
    appearance.avg_bbox_area_pct = 0.2
    appearance.avg_confidence = 0.9
    appearance.rejected_reason = None
    appearance.has_narration_mention = False
    appearance.has_ocr_overlap = False
    monkeypatch.setattr(
        runner,
        "_load_appearances_for_catalog",
        AsyncMock(return_value=[appearance]),
    )
    create_render = AsyncMock()
    monkeypatch.setattr(runner, "_create_render_job", create_render)

    lease = MagicMock()
    lease.set_stage = MagicMock()
    lease.heartbeat_now = AsyncMock(return_value=False)

    await runner._process_claimed_child_payload(child_id=child_id, lease=lease)

    lease.set_stage.assert_called_once()
    lease.heartbeat_now.assert_awaited_once()
    create_render.assert_not_awaited()


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
    # PR 3: the default self-heal-on path uses
    # ``find_claimable_render_children`` instead of the legacy
    # ``find_queued_render_children``. Mock both so this test stays
    # consistent regardless of which branch the runner takes (and the
    # legacy mock keeps working if a future revert flips the flag off).
    fake_repo.find_claimable_render_children = AsyncMock(
        side_effect=[queued, [], [], [], []],
    )
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


# ======================================================================
# eager parent promotion (_try_promote_parent_for_child) — PR 2
# ======================================================================
#
# Plan ref: .claude/plans/shorts-auto-product-cap-stuck-fix.md (PR 2 of 3).
# The helper fires after every child terminal transition. Tests cover:
#   * flag-off short-circuits before any DB activity
#   * parent_id_hint skips the get_internal lookup
#   * no hint → look up child to find parent_job_id
#   * defensive paths: missing child, child without parent
#   * exceptions are swallowed (the child's terminal write is durable;
#     a promotion error must NEVER raise back to the caller)
#   * scan_order_parent_auto_promoted log only fires on success


class TestTryPromoteParentForChild:
    @pytest.mark.asyncio
    async def test_disabled_via_flag_returns_immediately(self, monkeypatch):
        """When the kill switch is off, the helper does NOT touch the
        DB at all — no session opened, no repo methods called. This
        is the emergency-disable path documented in the plan.
        """
        s = _settings_stub(eager_promotion_enabled=False)
        runner, fake_repo = _build_runner(monkeypatch, settings=s)

        await runner._try_promote_parent_for_child(
            child_id=uuid4(), parent_id_hint=uuid4(),
        )

        fake_repo.try_promote_parent_if_all_children_terminal.assert_not_awaited()
        fake_repo.get_internal.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_uses_parent_id_hint_skipping_lookup(self, monkeypatch):
        """Hot-path optimization: when the caller has parent_id loaded
        already (success paths in _process_child_payload /
        _process_child_stt), skip the redundant get_internal call.
        """
        runner, fake_repo = _build_runner(monkeypatch)
        parent_id = uuid4()
        await runner._try_promote_parent_for_child(
            child_id=uuid4(), parent_id_hint=parent_id,
        )
        fake_repo.get_internal.assert_not_awaited()
        fake_repo.try_promote_parent_if_all_children_terminal.assert_awaited_once_with(
            parent_job_id=parent_id,
        )

    @pytest.mark.asyncio
    async def test_looks_up_parent_when_no_hint(self, monkeypatch):
        """Cold-path fallback: catch-all failure callers
        (_complete_no_render / _mark_child_failed) don't have parent
        loaded; the helper does ONE extra get_internal lookup.
        """
        runner, fake_repo = _build_runner(monkeypatch)
        parent_id = uuid4()
        child_id = uuid4()
        child = MagicMock()
        child.parent_job_id = parent_id
        fake_repo.get_internal = AsyncMock(return_value=child)

        await runner._try_promote_parent_for_child(child_id=child_id)

        fake_repo.get_internal.assert_awaited_once_with(job_id=child_id)
        fake_repo.try_promote_parent_if_all_children_terminal.assert_awaited_once_with(
            parent_job_id=parent_id,
        )

    @pytest.mark.asyncio
    async def test_no_op_when_child_missing(self, monkeypatch):
        """Defensive: if the child row vanished between terminal
        write and promotion attempt, do nothing rather than crashing
        the caller (which has already committed)."""
        runner, fake_repo = _build_runner(monkeypatch)
        fake_repo.get_internal = AsyncMock(return_value=None)

        await runner._try_promote_parent_for_child(child_id=uuid4())

        fake_repo.try_promote_parent_if_all_children_terminal.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_op_when_child_has_no_parent(self, monkeypatch):
        """Defensive: schema invariant says render_child rows always
        have parent_job_id, but if the row was somehow corrupted, the
        helper bails rather than promote with a None parent_id."""
        runner, fake_repo = _build_runner(monkeypatch)
        child = MagicMock()
        child.parent_job_id = None
        fake_repo.get_internal = AsyncMock(return_value=child)

        await runner._try_promote_parent_for_child(child_id=uuid4())

        fake_repo.try_promote_parent_if_all_children_terminal.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_swallows_exception_from_repo(self, monkeypatch):
        """A promotion error MUST NOT raise back to the caller — the
        caller has already committed the child's terminal stage. If
        promotion fails, the lazy block in get_scan_order_status is
        the safety net.
        """
        runner, fake_repo = _build_runner(monkeypatch)
        fake_repo.try_promote_parent_if_all_children_terminal = AsyncMock(
            side_effect=RuntimeError("DB transient"),
        )

        # MUST NOT raise.
        await runner._try_promote_parent_for_child(
            child_id=uuid4(), parent_id_hint=uuid4(),
        )

    @pytest.mark.asyncio
    async def test_logs_when_promotion_succeeds(self, monkeypatch, caplog):
        """The scan_order_parent_auto_promoted log line is the
        observability hook for plan §Validation gate 1.E (eager
        dominates lazy)."""
        import logging

        runner, fake_repo = _build_runner(monkeypatch)
        fake_repo.try_promote_parent_if_all_children_terminal = AsyncMock(
            return_value=MagicMock(),  # truthy = promoted
        )

        with caplog.at_level(
            logging.INFO,
            logger="app.modules.shorts_auto_product.children.runner",
        ):
            await runner._try_promote_parent_for_child(
                child_id=uuid4(), parent_id_hint=uuid4(),
            )

        assert any(
            "scan_order_parent_auto_promoted" in r.message for r in caplog.records
        )

    @pytest.mark.asyncio
    async def test_no_log_when_promotion_returns_none(self, monkeypatch, caplog):
        """When the atomic UPDATE returns no row (parent already
        terminal, race-loss, etc.) we MUST NOT log the
        scan_order_parent_auto_promoted event — that would mislead
        metrics by counting non-promotions."""
        import logging

        runner, fake_repo = _build_runner(monkeypatch)
        fake_repo.try_promote_parent_if_all_children_terminal = AsyncMock(
            return_value=None,
        )

        with caplog.at_level(
            logging.INFO,
            logger="app.modules.shorts_auto_product.children.runner",
        ):
            await runner._try_promote_parent_for_child(
                child_id=uuid4(), parent_id_hint=uuid4(),
            )

        assert not any(
            "scan_order_parent_auto_promoted" in r.message for r in caplog.records
        )


# ======================================================================
# self-healing runner — PR 3
# ======================================================================
#
# Plan ref: .claude/plans/shorts-auto-product-cap-stuck-fix.md (PR 3 of 3).
# Tests cover:
#   * _poll_and_dispatch branches on auto_shorts_product_v2_self_heal_enabled
#   * Re-claim warning fires when started_at < claimed_at
#   * Fresh claims (started_at == claimed_at) don't fire the warning
#   * Defensive isinstance-datetime check tolerates non-datetime values


class TestSelfHealingRunner:
    @pytest.mark.asyncio
    async def test_self_heal_enabled_polls_claimable(self, monkeypatch):
        """Default flag-on: poll uses find_claimable_render_children."""
        s = _settings_stub()  # eager + self_heal both default True
        runner, fake_repo = _build_runner(monkeypatch, settings=s)

        await runner._poll_and_dispatch()

        fake_repo.find_claimable_render_children.assert_awaited_once()
        fake_repo.find_queued_render_children.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_self_heal_disabled_falls_back_to_legacy_poll(
        self, monkeypatch,
    ):
        """Flag-off: poll falls back to find_queued_render_children
        (the legacy queued-only shim)."""
        s = _settings_stub()
        s.auto_shorts_product_v2_self_heal_enabled = False
        runner, fake_repo = _build_runner(monkeypatch, settings=s)

        await runner._poll_and_dispatch()

        fake_repo.find_queued_render_children.assert_awaited_once()
        fake_repo.find_claimable_render_children.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_re_claim_logs_warning_when_started_at_precedes_claimed_at(
        self, monkeypatch, caplog,
    ):
        """The runner's re-claim detector: claim() preserved
        started_at on re-claim, so started_at < claimed_at uniquely
        identifies a re-claim. Verify the warning fires + carries the
        original timestamp for forensics."""
        import logging
        from datetime import datetime, timedelta, timezone

        runner, fake_repo = _build_runner(monkeypatch)

        original_start = datetime.now(timezone.utc) - timedelta(minutes=10)
        re_claim_now = datetime.now(timezone.utc)
        claimed = MagicMock()
        claimed.started_at = original_start
        claimed.claimed_at = re_claim_now
        fake_repo.claim = AsyncMock(return_value=claimed)

        # Force the no-render branch — _process_child_payload exits
        # cleanly after the claim block, which is all we care about.
        monkeypatch.setattr(
            runner, "_load_child_context", AsyncMock(return_value=None),
        )

        with caplog.at_level(
            logging.WARNING,
            logger="app.modules.shorts_auto_product.children.runner",
        ):
            await runner._process_child_payload(uuid4())

        warnings = [
            r for r in caplog.records
            if "child_re_claimed_after_lease_expiry" in r.message
        ]
        assert len(warnings) == 1, (
            f"Expected exactly one re-claim warning, got: {warnings}"
        )

    @pytest.mark.asyncio
    async def test_fresh_claim_does_not_log_re_claim_warning(
        self, monkeypatch, caplog,
    ):
        """Fresh claim: claim() sets both started_at and claimed_at
        to NOW. started_at == claimed_at → no `<` → no warning. The
        equality is a strict-`<` check so we don't get false
        positives on every fresh claim."""
        import logging
        from datetime import datetime, timezone

        runner, fake_repo = _build_runner(monkeypatch)

        same_now = datetime.now(timezone.utc)
        claimed = MagicMock()
        claimed.started_at = same_now
        claimed.claimed_at = same_now
        fake_repo.claim = AsyncMock(return_value=claimed)
        monkeypatch.setattr(
            runner, "_load_child_context", AsyncMock(return_value=None),
        )

        with caplog.at_level(
            logging.WARNING,
            logger="app.modules.shorts_auto_product.children.runner",
        ):
            await runner._process_child_payload(uuid4())

        assert not any(
            "child_re_claimed_after_lease_expiry" in r.message
            for r in caplog.records
        )

    @pytest.mark.asyncio
    async def test_re_claim_check_tolerates_non_datetime_values(
        self, monkeypatch,
    ):
        """Defensive: the runner's isinstance(datetime) guards must
        absorb non-datetime values (test fakes, unexpected DB shape)
        without raising. The warning is best-effort observability —
        it must NEVER crash _process_child_payload."""
        runner, fake_repo = _build_runner(monkeypatch)

        # Bare MagicMocks — Python 3.11 raises TypeError on `<`
        # between MagicMocks. Without the isinstance guards this
        # would crash the runner's claim block.
        claimed = MagicMock()
        # Don't override started_at/claimed_at — they default to
        # MagicMock, which is the failure case we want to absorb.
        fake_repo.claim = AsyncMock(return_value=claimed)
        monkeypatch.setattr(
            runner, "_load_child_context", AsyncMock(return_value=None),
        )

        # MUST NOT raise.
        await runner._process_child_payload(uuid4())


# ======================================================================
# PR 1 of multi-product wizard — pre-assigned catalog_entry_id is honored
# ======================================================================
#
# Pre-PR-1 latent bug: parent.catalog_entry_id was set on single-pick
# wizard submissions but the api-process runner ignored it and
# round-robined across the whole catalog. PR 1 propagates the pick to
# each child at fan-out (in service.py) and the runner now reads
# child.catalog_entry_id directly when set.
#
# Plan: ``.claude/plans/wizard-multi-product-select.md`` (PR 1 of 3).


class TestPreAssignedCatalogEntryId:
    """Verify the runner honors child.catalog_entry_id when set,
    and falls back to the picker when it's None or stale."""

    def _make_parent_and_child(self, *, child_catalog_id, lookup):
        """Build a (child, parent, catalog_label_lookup) tuple for
        ``_load_child_context`` to return, plus the fake child that
        repo.claim returns."""
        from datetime import datetime, timezone

        from app.modules.shorts_auto_product.models import (
            PRODUCT_DISTRIBUTION_SINGLE,
        )

        now = datetime.now(timezone.utc)
        parent = MagicMock()
        parent.id = uuid4()
        parent.org_id = uuid4()
        parent.video_id = uuid4()
        parent.length_seconds = 60
        parent.duration_preset_sec = 60
        parent.requested_by_user_id = uuid4()
        parent.product_distribution = PRODUCT_DISTRIBUTION_SINGLE

        child = MagicMock()
        child.id = uuid4()
        child.parent_job_id = parent.id
        child.shorts_index = 1
        child.catalog_entry_id = child_catalog_id
        child.started_at = now
        child.claimed_at = now
        return child, parent, lookup

    @pytest.mark.asyncio
    async def test_pre_assigned_id_used_when_in_active_catalog(
        self, monkeypatch,
    ):
        """Wizard single-pick: child has catalog_entry_id=X, the active
        catalog contains X. Runner uses X directly and does NOT
        round-robin via the picker."""
        s = _settings_stub()
        s.auto_shorts_product_v2_track_mode = "sam2"  # exercise SAM2 picker path
        runner, fake_repo = _build_runner(monkeypatch, settings=s)

        target_id = uuid4()
        other_id = uuid4()
        # Lookup contains BOTH the pre-assigned id and another, so a
        # picker round-robin would have a chance to pick the wrong one.
        lookup = {target_id: "Product Target", other_id: "Product Other"}
        child, parent, _ = self._make_parent_and_child(
            child_catalog_id=target_id, lookup=lookup,
        )
        fake_repo.claim = AsyncMock(return_value=child)

        monkeypatch.setattr(
            runner,
            "_load_child_context",
            AsyncMock(return_value=(child, parent, lookup, {k: [v] for k, v in lookup.items()})),
        )

        # Capture which catalog_entry_id reaches _load_appearances_for_catalog.
        # Empty appearances → clean exit via _complete_no_render.
        captured = {}

        async def fake_load(*, org_id, catalog_entry_id):
            captured["catalog_entry_id"] = catalog_entry_id
            return []
        monkeypatch.setattr(
            runner, "_load_appearances_for_catalog", AsyncMock(side_effect=fake_load),
        )

        await runner._process_child_payload(child.id)

        assert captured.get("catalog_entry_id") == target_id, (
            f"Expected runner to honor pre-assigned id {target_id}, "
            f"got {captured.get('catalog_entry_id')} instead"
        )

    @pytest.mark.asyncio
    async def test_falls_back_to_picker_when_pre_assigned_id_was_rejected(
        self, monkeypatch, caplog,
    ):
        """Defensive: if a catalog entry was soft-rejected between
        fan-out and runner pickup, the lookup no longer contains it.
        Runner must fall back to the picker round-robin so the user
        gets *some* short instead of stalling."""
        import logging

        s = _settings_stub()
        s.auto_shorts_product_v2_track_mode = "sam2"
        runner, fake_repo = _build_runner(monkeypatch, settings=s)

        stale_id = uuid4()  # was assigned at fan-out
        other_id = uuid4()  # only this one is in the active catalog now
        lookup = {other_id: "Only Survivor"}
        child, parent, _ = self._make_parent_and_child(
            child_catalog_id=stale_id, lookup=lookup,
        )
        fake_repo.claim = AsyncMock(return_value=child)

        monkeypatch.setattr(
            runner,
            "_load_child_context",
            AsyncMock(return_value=(child, parent, lookup, {k: [v] for k, v in lookup.items()})),
        )

        captured = {}

        async def fake_load(*, org_id, catalog_entry_id):
            captured["catalog_entry_id"] = catalog_entry_id
            return []
        monkeypatch.setattr(
            runner, "_load_appearances_for_catalog", AsyncMock(side_effect=fake_load),
        )

        with caplog.at_level(
            logging.WARNING,
            logger="app.modules.shorts_auto_product.children.runner",
        ):
            await runner._process_child_payload(child.id)

        # Picker fallback ran — captured id is the survivor (only key
        # in the lookup), NOT the stale pre-assigned id.
        assert captured.get("catalog_entry_id") == other_id, (
            f"Expected fallback to surviving id {other_id}, got {captured.get('catalog_entry_id')}"
        )
        # Warning logged so we can quantify staleness in prod.
        assert any(
            "child_pre_assigned_catalog_entry_unavailable" in r.message
            for r in caplog.records
        ), "Expected staleness warning to be logged"

    @pytest.mark.asyncio
    async def test_legacy_no_pre_assignment_uses_picker(self, monkeypatch):
        """Whole-catalog mode (legacy default): child.catalog_entry_id
        is None → runner uses the picker round-robin. No regression
        for existing wizards that didn't pick a product."""
        s = _settings_stub()
        s.auto_shorts_product_v2_track_mode = "sam2"
        runner, fake_repo = _build_runner(monkeypatch, settings=s)

        a, b = uuid4(), uuid4()
        lookup = {a: "A", b: "B"}
        child, parent, _ = self._make_parent_and_child(
            child_catalog_id=None,  # legacy mode
            lookup=lookup,
        )
        fake_repo.claim = AsyncMock(return_value=child)

        monkeypatch.setattr(
            runner,
            "_load_child_context",
            AsyncMock(return_value=(child, parent, lookup, {k: [v] for k, v in lookup.items()})),
        )

        captured = {}

        async def fake_load(*, org_id, catalog_entry_id):
            captured["catalog_entry_id"] = catalog_entry_id
            return []
        monkeypatch.setattr(
            runner, "_load_appearances_for_catalog", AsyncMock(side_effect=fake_load),
        )

        await runner._process_child_payload(child.id)

        # Picker chose one of {a, b}. We don't assert which (picker is
        # deterministic on shorts_index but that's an implementation
        # detail) — the contract is that SOME id from the lookup is
        # used, NOT None.
        assert captured.get("catalog_entry_id") in {a, b}
