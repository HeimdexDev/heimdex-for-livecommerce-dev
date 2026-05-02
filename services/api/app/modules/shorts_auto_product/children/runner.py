"""Wizard child runner — Phase 4 PR #4.

Long-lived asyncio background task that picks up queued
``mode='render_child'`` rows produced by the parent fan-out hook
(``internal_router.complete``), claims them via the existing
DB-atomic lease machinery, and processes them.

## Architecture

* **Single instance per API replica.** The runner is started once in
  ``app.main:lifespan``. Multiple replicas of the API run multiple
  runners concurrently; the DB-atomic ``ProductScanJobRepository.claim``
  is the race resolver — exactly one replica wins each child.
* **Bounded concurrency** via ``asyncio.Semaphore``. Default 4 per
  replica (tunable via ``auto_shorts_product_v2_child_runner_max_concurrency``).
* **Polling cadence** = 5s (tunable). The poll query is cheap (partial
  index ``ix_product_scan_jobs_child_queue`` covers it) so we can
  afford a short interval without burning DB cycles on idle replicas.
* **No work-stealing across replicas mid-flight**. Once a replica
  claims a child, the lease (default 300s) gives it that long to
  /complete. If it crashes mid-flight, the lease eventually expires
  and another replica re-claims via the same poll path.

## Loose-coupling boundary (plan §15)

The runner imports:

* ``app.modules.shorts_auto_product.repositories.job`` — its own module's repo.
* ``app.modules.shorts_auto_product.models`` — its own module's constants.
* ``app.db.base.get_async_session_factory`` — the shared async session
  factory (used by every background task in this codebase, mirrors
  ``app.modules.worker_events.recorder``).
* ``app.config.Settings`` — read-only.
* ``app.logging_config`` — structured logger.

The runner does NOT import:

* Any other ``app.modules.*`` package (no cross-module coupling).
* ``heimdex_media_pipelines`` directly in this PR — the picker
  integration is wired in PR #5 alongside the worker refactor that
  populates parent appearances. PR #4 keeps the runner pipeline-lib-free
  so the API doesn't grow a new ML dependency until the worker side
  is ready to feed it real data.

## Phase 4 PR #4 stub semantics

PR #4 ships the **infrastructure only**. The processing step is
deliberately stubbed: claim → noop → /complete with
``render_job_id=None``. This:

* Proves the runner's claim race + bounded concurrency + lease lifecycle
  work end-to-end.
* Lets the wizard frontend (PR #6) be developed against a runner that
  actually transitions children through the full state machine.
* Avoids dragging the heimdex-media-pipelines dependency into the API
  service before contracts v0.14.0 ships in PR #5.

PR #5 replaces the stub with the real picker + stitch-plan + render
service call. The dispatch is intentionally narrow (one method —
``_process_child_payload``) so PR #5's diff is contained.

The runner is gated behind ``auto_shorts_product_v2_child_runner_enabled``
which **defaults to True** but is easy to flip off if PR #4 rolls out
ahead of the rest of the wizard surface area.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import AsyncIterator, Awaitable, Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.modules.shorts_auto_product.models import (
    SCAN_STAGE_ASSEMBLING,
)
from app.modules.shorts_auto_product.repositories.job import (
    ProductScanJobRepository,
)

logger = logging.getLogger(__name__)


# Type alias for an async session-yielding callable. Production wires
# this to ``app.db.base.get_async_session_factory()``; tests inject a
# stub that yields a mock session.
SessionFactory = Callable[[], AsyncIterator[AsyncSession]]


def _default_instance_id() -> str:
    """Identifier embedded in ``claimed_by`` so logs trace which API
    replica processed a given child. ``HOSTNAME`` is set by every
    container runtime we deploy on (Docker, Aircloud, ECS); fall
    back to the OS hostname for dev.
    """
    return os.getenv("HOSTNAME") or socket.gethostname() or "api-unknown"


class ChildRunner:
    """In-API-process child runner for the Phase 4 wizard.

    Lifecycle:

      1. ``start()`` schedules the main loop as an asyncio task and
         returns immediately. The caller (app.main:lifespan) awaits
         the returned task at shutdown.
      2. The loop polls every ``poll_seconds`` for queued children,
         dispatches them via ``asyncio.create_task`` under the bounded
         semaphore.
      3. ``stop()`` sets the shutdown event. The loop exits at the
         next poll boundary; in-flight tasks finish their current
         iteration (lease-protected, so a hard kill at this point
         would just cause the lease to expire and another replica
         to re-claim — no orphaned rows).
    """

    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        instance_id: str | None = None,
        process_child_fn: Callable[[UUID], Awaitable[None]] | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.instance_id = instance_id or _default_instance_id()
        # Allow tests to inject a fake processor that doesn't actually
        # call repo / render service. Production callers leave this
        # None and the real ``_process_child_payload`` runs.
        self._process_child_fn = process_child_fn or self._process_child_payload
        self._stop_event = asyncio.Event()
        self._semaphore = asyncio.Semaphore(
            settings.auto_shorts_product_v2_child_runner_max_concurrency
        )
        self._task: asyncio.Task[None] | None = None
        self._inflight: set[asyncio.Task[None]] = set()

    @property
    def claimed_by(self) -> str:
        """Identifier persisted on ``ProductScanJob.claimed_by`` —
        ``api-child-{instance_id}``. The ``api-child-`` prefix
        distinguishes this runner from worker-side claims (which use
        ``settings.worker_id``).
        """
        return f"api-child-{self.instance_id}"

    def start(self) -> asyncio.Task[None]:
        """Schedule the main loop. Idempotent — calling start twice
        on the same instance is a no-op (returns the existing task).
        """
        if self._task is not None and not self._task.done():
            return self._task
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._loop(), name="shorts-child-runner")
        return self._task

    async def stop(self, *, drain_timeout_seconds: float = 30.0) -> None:
        """Request shutdown. Waits up to ``drain_timeout_seconds`` for
        in-flight children to complete; tasks still running after the
        timeout will be cancelled (the lease will eventually expire
        and another replica will re-claim).
        """
        self._stop_event.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=drain_timeout_seconds)
            except asyncio.TimeoutError:
                logger.warning(
                    "child_runner_stop_timeout_cancelling",
                    extra={
                        "drain_timeout_seconds": drain_timeout_seconds,
                        "inflight": len(self._inflight),
                    },
                )
                self._task.cancel()
                # Best-effort cancel of in-flight per-child tasks.
                for t in list(self._inflight):
                    t.cancel()

    async def _loop(self) -> None:
        """Main poll loop. Exits when ``_stop_event`` is set."""
        poll_seconds = self.settings.auto_shorts_product_v2_child_runner_poll_seconds
        if not self.settings.auto_shorts_product_v2_child_runner_enabled:
            logger.info(
                "child_runner_disabled_at_boot",
                extra={
                    "reason": "AUTO_SHORTS_PRODUCT_V2_CHILD_RUNNER_ENABLED is False",
                },
            )
            return

        logger.info(
            "child_runner_started",
            extra={
                "instance_id": self.instance_id,
                "max_concurrency": (
                    self.settings.auto_shorts_product_v2_child_runner_max_concurrency
                ),
                "poll_seconds": poll_seconds,
            },
        )
        while not self._stop_event.is_set():
            try:
                await self._poll_and_dispatch()
            except Exception:
                logger.exception(
                    "child_runner_poll_iteration_failed",
                    extra={"instance_id": self.instance_id},
                )
                # Don't let a single failed poll kill the loop. Sleep
                # before retrying so we don't hot-loop on a persistent
                # error (e.g. DB outage).

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=poll_seconds,
                )
            except asyncio.TimeoutError:
                # Normal poll-interval expiry — continue.
                pass

        # Drain in-flight tasks before returning.
        if self._inflight:
            logger.info(
                "child_runner_draining",
                extra={"inflight": len(self._inflight)},
            )
            await asyncio.gather(*self._inflight, return_exceptions=True)

        logger.info(
            "child_runner_stopped",
            extra={"instance_id": self.instance_id},
        )

    async def _poll_and_dispatch(self) -> None:
        """One poll iteration.

        Reads up to ``max_concurrency * 2`` candidate child ids in
        FIFO order (no DB lock — claim is the race resolver) and
        dispatches each as an asyncio task. The semaphore bounds
        actual concurrent processing.
        """
        max_concurrency = (
            self.settings.auto_shorts_product_v2_child_runner_max_concurrency
        )
        async with self.session_factory() as session:
            repo = ProductScanJobRepository(session)
            candidates = await repo.find_queued_render_children(
                limit=max_concurrency * 2,
            )
        for child_id in candidates:
            task = asyncio.create_task(self._run_one_child(child_id))
            self._inflight.add(task)
            task.add_done_callback(self._inflight.discard)

    async def _run_one_child(self, child_id: UUID) -> None:
        """Per-child wrapper that respects the bounded semaphore and
        catches exceptions so one bad child can't kill the loop.
        """
        async with self._semaphore:
            try:
                await self._process_child_fn(child_id)
            except Exception:
                logger.exception(
                    "child_runner_process_child_failed",
                    extra={
                        "child_id": str(child_id),
                        "instance_id": self.instance_id,
                    },
                )
                # Best-effort: try to mark the child as failed so it
                # doesn't get re-polled forever. If even this fails,
                # the lease will eventually expire and another replica
                # will retry.
                await self._mark_child_failed(
                    child_id=child_id,
                    error_message="child runner crashed mid-process",
                )

    async def _process_child_payload(self, child_id: UUID) -> None:
        """The actual child-processing step.

        **Phase 4 PR #4 stub**: claim → /complete with
        ``render_job_id=None``. Real picker + render-service call
        lands in PR #5.

        The split of repo work across two transactions (claim ↔
        complete) is intentional:

          * The first transaction commits the claim so the row is
            visible as ``claimed_by=api-child-…`` to other replicas.
            Without this commit, two replicas could each see the
            row as queued and both try to claim — though the second
            UPDATE would still fail and return None, the wasted
            poll cycle is avoidable.
          * The second transaction holds the actual work + /complete.
            PR #5 will widen this transaction to include the picker
            cost rollup and render-service call.
        """
        # ── 1. Claim ──────────────────────────────────────────────
        async with self.session_factory() as session:
            repo = ProductScanJobRepository(session)
            claimed = await repo.claim(
                job_id=child_id,
                claimed_by=self.claimed_by,
                lease_seconds=(
                    self.settings.auto_shorts_product_v2_child_lease_seconds
                ),
                next_stage=SCAN_STAGE_ASSEMBLING,
            )
            if claimed is None:
                # Another replica already claimed this child OR the
                # row is no longer in 'queued' (already processed,
                # cancelled, etc.). No-op.
                logger.debug(
                    "child_already_claimed_or_terminal",
                    extra={
                        "child_id": str(child_id),
                        "instance_id": self.instance_id,
                    },
                )
                return
            await session.commit()

        # ── 2. Stub work (PR #4) ──────────────────────────────────
        # PR #5 replaces this section with:
        #   - read parent + active appearances
        #   - run select_subset / build_stitch_plan via heimdex_media_pipelines
        #   - call shorts_render_service.create_render_job
        #   - persist render_job_id in the /complete call below
        logger.info(
            "child_runner_processed_child_stub",
            extra={
                "child_id": str(child_id),
                "instance_id": self.instance_id,
                "note": "PR #4 stub; real render integration pending PR #5",
            },
        )

        # ── 3. Complete ───────────────────────────────────────────
        async with self.session_factory() as session:
            repo = ProductScanJobRepository(session)
            completed = await repo.complete_tracking(
                job_id=child_id,
                claimed_by=self.claimed_by,
                cost_delta_usd=Decimal("0"),
                # PR #5: replace with the actual ShortsRenderJob.id from
                # the render service. None for now means the wizard UI
                # shows "render not produced" — acceptable for the stub.
                render_job_id=None,
            )
            if completed is None:
                # Lease lost between claim and complete (cancel cascade
                # ran, or this replica's clock skewed past the lease).
                # Nothing to do here; the row is in its terminal state
                # already.
                logger.warning(
                    "child_complete_lease_lost",
                    extra={
                        "child_id": str(child_id),
                        "instance_id": self.instance_id,
                    },
                )
                return
            await session.commit()

    async def _mark_child_failed(
        self,
        *,
        child_id: UUID,
        error_message: str,
    ) -> None:
        """Best-effort failure path for the catch-all handler."""
        try:
            async with self.session_factory() as session:
                repo = ProductScanJobRepository(session)
                await repo.fail(
                    job_id=child_id,
                    claimed_by=self.claimed_by,
                    error_code="internal_error",
                    error_message=error_message[:1900],
                    cost_delta_usd=Decimal("0"),
                )
                await session.commit()
        except Exception:
            logger.exception(
                "child_runner_mark_failed_failed",
                extra={"child_id": str(child_id)},
            )


def create_child_runner(
    *,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    instance_id: str | None = None,
) -> ChildRunner:
    """Factory used by ``app.main:lifespan``. Tests construct
    ``ChildRunner`` directly with their own session factory + injected
    ``process_child_fn``.
    """
    return ChildRunner(
        settings=settings,
        session_factory=session_factory,
        instance_id=instance_id,
    )
