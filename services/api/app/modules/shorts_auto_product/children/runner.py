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
from app.lib.product_track.config import TrackingConfig
from app.lib.product_track.stitching import build_stitch_plan
from app.lib.product_track.subset_selector import (
    GreedyPicker,
    ScoredWindow,
    score_windows,
    select_subset,
)
from app.modules.shorts_auto_product.children.composition import (
    build_composition_spec_from_stitch_plan,
)
from app.modules.shorts_auto_product.children.picker import (
    SingleProductSubsetPicker,
)
from app.modules.shorts_auto_product.children.scene_id_utils import (
    os_video_id_from_scene_id,
)
from app.modules.shorts_auto_product.models import (
    PRODUCT_DISTRIBUTION_SINGLE,
    SCAN_STAGE_ASSEMBLING,
    ProductAppearance,
    ProductScanJob,
)
from app.modules.shorts_auto_product.repositories.appearance import (
    ProductAppearanceRepository,
)
from app.modules.shorts_auto_product.repositories.catalog import (
    ProductCatalogRepository,
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
        scene_search_client: object,
        instance_id: str | None = None,
        process_child_fn: Callable[[UUID], Awaitable[None]] | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        # Production: ``app.state.scene_opensearch_client`` (set in
        # ``app.main:lifespan`` before ``ChildRunner.start()``). Tests
        # inject a no-op stub — only `_validate_scene_clips` (called
        # inside ``ShortsRenderService.create_render_job``) touches
        # this object, and tests typically inject the entire render
        # service via ``process_child_fn`` so the real OS client
        # isn't reached.
        # Typed as ``object`` deliberately: the prod client is
        # ``opensearchpy.AsyncOpenSearch`` but tests pass in
        # MagicMock instances; loose typing keeps both paths happy.
        self.scene_search_client = scene_search_client
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
        """The actual child-processing step (Phase 4 PR #6).

        Flow:

          1. Claim the child (queued → assembling).
          2. Read parent + active appearances + catalog set.
          3. Pick a catalog by round-robin on parent.shorts_index
             (Phase 4 single-product mode).
          4. Filter appearances to that catalog → score → select
             subset → build stitch plan.
          5. Build CompositionSpec via the typed adapter.
          6. Call ``ShortsRenderService.create_render_job`` directly
             (no self-HTTP — plan §15 carve-out).
          7. ``complete_tracking(render_job_id=…)`` to terminal.

        Multiple "no qualifying" outcomes (no catalogs, no
        appearances, picker returns []) all land at step 7 with
        ``render_job_id=None`` so the user-facing UI shows
        "no render produced" rather than "failed". Real failures
        (DB error, render service error) raise out of this method
        and are caught by ``_run_one_child``'s catch-all, which
        invokes ``_mark_child_failed``.

        Sessions are split across stages on purpose: claim commits
        immediately so the lease is visible to other replicas;
        render creation self-commits inside the service; completion
        is its own transaction. A crash between render creation
        and completion is partially mitigated by
        ``ShortsRenderService``'s 30s composition_hash dedupe — a
        retry with the same windows hits the dedupe and reuses the
        render row.
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
                logger.debug(
                    "child_already_claimed_or_terminal",
                    extra={
                        "child_id": str(child_id),
                        "instance_id": self.instance_id,
                    },
                )
                return
            await session.commit()

        # ── 2. Read child + parent + catalog set ──────────────────
        loaded = await self._load_child_context(child_id=child_id)
        if loaded is None:
            await self._complete_no_render(
                child_id=child_id,
                reason="no_catalog_or_parent",
            )
            return

        child, parent, catalog_label_lookup = loaded

        # ── 3. Pick a catalog for this child ──────────────────────
        # Phase 4 single-mode is the only path live; Phase 5
        # multi-mode lands a different orchestration that selects
        # catalogs differently.
        distribution = (
            parent.product_distribution or PRODUCT_DISTRIBUTION_SINGLE
        )
        if distribution != PRODUCT_DISTRIBUTION_SINGLE:
            # Defensive: the public router gates wizard submissions
            # to PRODUCT_DISTRIBUTION_SINGLE for now. If a multi-mode
            # row sneaks through, fail loudly so the operator sees
            # it rather than silently producing a single-mode short.
            raise NotImplementedError(
                f"product_distribution={distribution!r} not yet "
                f"implemented (Phase 5 deliverable)"
            )

        try:
            catalog_pick = SingleProductSubsetPicker().pick_catalog(
                catalog_ids=list(catalog_label_lookup.keys()),
                shorts_index=child.shorts_index or 1,
            )
        except ValueError:
            await self._complete_no_render(
                child_id=child_id,
                reason="picker_value_error",
            )
            return

        chosen_catalog_id = catalog_pick.catalog_entry_id
        catalog_label = catalog_label_lookup.get(chosen_catalog_id)

        # ── 3.5. Track-mode branch ────────────────────────────────
        # When ``auto_shorts_product_v2_track_mode='stt'`` the rest of
        # this method is replaced by the in-process STT pipeline
        # (``track_stt.service.assemble_stt_clip``). Default ``"sam2"``
        # preserves the existing path. See
        # ``.claude/plans/shorts-auto-product-stt-pivot.md`` PR 2.5.
        if (
            getattr(self.settings, "auto_shorts_product_v2_track_mode", "sam2")
            == "stt"
        ):
            await self._process_child_stt(
                child=child,
                parent=parent,
                chosen_catalog_id=chosen_catalog_id,
                catalog_label=catalog_label,
            )
            return

        # ── 4. Score + select windows for the chosen catalog ──────
        appearances = await self._load_appearances_for_catalog(
            org_id=parent.org_id, catalog_entry_id=chosen_catalog_id,
        )
        if not appearances:
            logger.info(
                "child_no_appearances_for_chosen_catalog",
                extra={
                    "child_id": str(child_id),
                    "catalog_entry_id": str(chosen_catalog_id),
                },
            )
            await self._complete_no_render(
                child_id=child_id,
                reason="no_appearances_for_catalog",
            )
            return

        annotated_windows = [
            _appearance_to_annotated_window(a) for a in appearances
        ]
        cfg = TrackingConfig()
        length_seconds = parent.length_seconds or parent.duration_preset_sec or 60
        scored = score_windows(
            annotated_windows,
            duration_preset_sec=length_seconds,
            config=cfg,
        )
        if not scored:
            await self._complete_no_render(
                child_id=child_id,
                reason="no_scored_windows",
            )
            return

        selected = select_subset(
            scored,
            picker=GreedyPicker(),
            duration_preset_sec=length_seconds,
            config=cfg,
        )
        if not selected:
            await self._complete_no_render(
                child_id=child_id,
                reason="picker_returned_empty",
            )
            return

        plan = build_stitch_plan(
            selected,
            duration_target_sec=length_seconds,
            config=cfg,
        )
        os_video_id = os_video_id_from_scene_id(
            plan.windows[0].window.scene_id,
        )
        composition_spec = build_composition_spec_from_stitch_plan(
            plan=plan, os_video_id=os_video_id,
        )

        # ── 5. Create render via the shorts-render service ────────
        # Pass ``str(child_id)`` as the dedupe idempotency key
        # (migration 057). Two different scan_jobs that happen to
        # produce identical compositions stay distinct rather than
        # collapsing into one render row — fixes the staging
        # 2026-05-06 collision where the LLM enumerator picked the
        # same product for clips 1 and 5.
        render_job_id = await self._create_render_job(
            org_id=parent.org_id,
            user_id=parent.requested_by_user_id,
            os_video_id=os_video_id,
            title=catalog_label,
            composition_spec=composition_spec,
            scan_job_id=child_id,
        )

        # ── 6. Complete with the new render_job_id ────────────────
        async with self.session_factory() as session:
            repo = ProductScanJobRepository(session)
            completed = await repo.complete_tracking(
                job_id=child_id,
                claimed_by=self.claimed_by,
                cost_delta_usd=Decimal("0"),
                render_job_id=render_job_id,
            )
            if completed is None:
                logger.warning(
                    "child_complete_lease_lost",
                    extra={
                        "child_id": str(child_id),
                        "instance_id": self.instance_id,
                        "render_job_id": str(render_job_id),
                    },
                )
                return
            await session.commit()
        logger.info(
            "child_runner_processed_child",
            extra={
                "child_id": str(child_id),
                "render_job_id": str(render_job_id),
                "catalog_entry_id": str(chosen_catalog_id),
                "shorts_index": child.shorts_index,
                "windows": len(plan.windows),
            },
        )
        # PR 2: eager parent promotion — when this child is the last
        # active sibling, promote parent fanned_out → committed in a
        # single atomic UPDATE. Lazy block in get_scan_order_status
        # stays as belt-and-suspenders. parent.id is in scope from
        # _load_child_context.
        await self._try_promote_parent_for_child(
            child_id=child_id, parent_id_hint=parent.id,
        )

    # ── STT track (PR 2.5) ───────────────────────────────────────────

    async def _process_child_stt(
        self,
        *,
        child: ProductScanJob,
        parent: ProductScanJob,
        chosen_catalog_id: UUID,
        catalog_label: str | None,
    ) -> None:
        """STT-track replacement for steps 4-6 of ``_process_child_payload``.

        Branched into when ``auto_shorts_product_v2_track_mode='stt'``.
        Loads the full catalog entry (we already have its label, but
        not ``llm_label`` + ``spoken_aliases``), resolves the
        ``os_video_id`` from ``drive_files``, constructs an
        AsyncOpenSearch + AsyncOpenAI per-call (simpler v1; revisit
        if profiling flags this — see plan §"Open question for PR 2.5"),
        and runs the STT pipeline.

        Error mapping:

        * :class:`NoMentionsFoundError` and
          :class:`TranscriptUnavailableError` → ``_complete_no_render``
          (terminal stage=done with ``render_job_id=None``). The wizard
          UI already surfaces "no render produced" friendly-error-style
          for the SAM2 ``no_appearances_for_catalog`` path; STT reuses
          that same DB shape so the frontend doesn't need a new branch.
        * :class:`SttPipelineError` (base / OS unreachable / render
          enqueue failed) → ``_mark_child_failed`` with descriptive
          message. Distinct from no-render because the user CAN retry.

        Imports the STT module lazily so the SAM2 path doesn't pay
        the import cost when track_mode='sam2'.
        """
        from openai import AsyncOpenAI

        from app.modules.shorts_auto_product.track_stt import service as stt_service
        from app.modules.shorts_auto_product.track_stt.errors import (
            NoMentionsFoundError,
            SttPipelineError,
            TranscriptUnavailableError,
        )

        # ── 1. Load full catalog entry + os_video_id resolution ────
        os_video_id, llm_label, spoken_aliases = await self._load_stt_inputs(
            org_id=parent.org_id,
            catalog_entry_id=chosen_catalog_id,
            drive_file_id=parent.video_id,
        )
        if os_video_id is None or llm_label is None:
            # Catalog entry vanished between picker and load (rare),
            # or the drive_files row is missing. Either way, no
            # render to produce.
            await self._complete_no_render(
                child_id=child.id,
                reason="stt_inputs_missing",
            )
            return

        length_seconds = (
            parent.length_seconds
            or parent.duration_preset_sec
            or 60
        )
        target_duration_ms = int(length_seconds) * 1000

        # ── 2. Construct per-call clients ──────────────────────────
        os_client = self._build_os_client()
        openai_client = AsyncOpenAI(
            api_key=getattr(self.settings, "openai_api_key", "") or "",
            timeout=15.0,
        )

        # ── 3. Build the enqueue_render closure ────────────────────
        # Captures parent + child + os_video_id by closure so
        # track_stt itself never sees DB-row internals. Mirrors the
        # existing ``_create_render_job`` call in the SAM2 path —
        # both paths must forward ``scan_job_id`` so render dedupe
        # is scoped per scan_job (migration 057).
        async def _enqueue_render(spec) -> UUID:
            return await self._create_render_job(
                org_id=parent.org_id,
                user_id=parent.requested_by_user_id,
                os_video_id=os_video_id,  # type: ignore[arg-type]
                title=catalog_label,
                composition_spec=spec,
                scan_job_id=child.id,
            )

        # ── 4. Run the pipeline ────────────────────────────────────
        try:
            try:
                # Lazy import to avoid loading the storyboard
                # submodule (and its enum + Protocol machinery)
                # on the hot SAM2 path where it's not used.
                from app.modules.shorts_auto_product.track_stt.storyboard import (
                    build_storyboard_picker_from_settings,
                )

                storyboard_picker = build_storyboard_picker_from_settings(
                    self.settings,
                )
                result = await stt_service.assemble_stt_clip(
                    org_id=parent.org_id,
                    catalog_entry_id=chosen_catalog_id,
                    llm_label=llm_label,
                    spoken_aliases=list(spoken_aliases or []),
                    os_video_id=os_video_id,
                    target_duration_ms=target_duration_ms,
                    title=catalog_label,
                    os_client=os_client,
                    openai_client=openai_client,
                    enqueue_render=_enqueue_render,
                    legacy_os_subtitles_enabled=getattr(
                        self.settings,
                        "auto_shorts_product_v2_legacy_os_subtitles_enabled",
                        False,
                    ),
                    storyboard_picker=storyboard_picker,
                    storyboard_shadow_mode=getattr(
                        self.settings,
                        "auto_shorts_product_v2_storyboard_shadow_mode",
                        False,
                    ),
                )
            except NoMentionsFoundError as e:
                logger.info(
                    "stt_runner_no_mentions",
                    extra={
                        "child_id": str(child.id),
                        "catalog_entry_id": str(chosen_catalog_id),
                        "video_id": os_video_id,
                        "reason": str(e)[:200],
                    },
                )
                await self._complete_no_render(
                    child_id=child.id,
                    reason="stt_no_mentions",
                )
                return
            except TranscriptUnavailableError as e:
                logger.info(
                    "stt_runner_transcript_unavailable",
                    extra={
                        "child_id": str(child.id),
                        "video_id": os_video_id,
                        "reason": str(e)[:200],
                    },
                )
                await self._complete_no_render(
                    child_id=child.id,
                    reason="stt_transcript_unavailable",
                )
                return
            except SttPipelineError as e:
                logger.warning(
                    "stt_runner_pipeline_error",
                    extra={
                        "child_id": str(child.id),
                        "video_id": os_video_id,
                        "error": str(e)[:300],
                    },
                )
                await self._mark_child_failed(
                    child_id=child.id,
                    error_message=f"stt pipeline failed: {e}"[:1900],
                )
                return
        finally:
            # AsyncOpenSearch / AsyncOpenAI both expose ``.close``;
            # swallow exceptions so a teardown error doesn't mask a
            # successful run.
            for client in (os_client, openai_client):
                close = getattr(client, "close", None)
                if close is None:
                    continue
                try:
                    maybe_awaitable = close()
                    if hasattr(maybe_awaitable, "__await__"):
                        await maybe_awaitable
                except Exception:  # noqa: BLE001 — teardown best-effort
                    pass

        # ── 5. Mark terminal with the produced render_job_id ───────
        async with self.session_factory() as session:
            repo = ProductScanJobRepository(session)
            completed = await repo.complete_tracking(
                job_id=child.id,
                claimed_by=self.claimed_by,
                cost_delta_usd=Decimal("0"),
                render_job_id=result.render_job_id,
            )
            if completed is None:
                logger.warning(
                    "stt_runner_complete_lease_lost",
                    extra={
                        "child_id": str(child.id),
                        "instance_id": self.instance_id,
                        "render_job_id": str(result.render_job_id),
                    },
                )
                return
            await session.commit()
        logger.info(
            "stt_runner_processed_child",
            extra={
                "child_id": str(child.id),
                "render_job_id": str(result.render_job_id),
                "catalog_entry_id": str(chosen_catalog_id),
                "shorts_index": child.shorts_index,
                "mentioned_scene_count": result.mentioned_scene_count,
                "matched_alias_count": len(result.matched_aliases),
            },
        )
        # PR 2: eager parent promotion (same shape as SAM2 path).
        await self._try_promote_parent_for_child(
            child_id=child.id, parent_id_hint=parent.id,
        )

    async def _load_stt_inputs(
        self,
        *,
        org_id: UUID,
        catalog_entry_id: UUID,
        drive_file_id: UUID,
    ) -> tuple[str | None, str | None, list[str]]:
        """Load (os_video_id, llm_label, spoken_aliases) for the STT
        pipeline. Read-only, single session.

        Returns ``(None, None, [])`` if either the catalog entry or
        the drive_file row is missing — caller routes to
        ``_complete_no_render`` rather than failing the child.
        """
        from sqlalchemy import select as _select

        # Lazy local import to keep DriveFile out of the runner's
        # module-level import graph until the STT path is taken.
        from app.modules.drive.models import DriveFile

        async with self.session_factory() as session:
            catalog_repo = ProductCatalogRepository(session)
            entry = await catalog_repo.get(
                org_id=org_id, entry_id=catalog_entry_id,
            )
            if entry is None:
                return None, None, []
            drive_row = await session.execute(
                _select(DriveFile).where(DriveFile.id == drive_file_id),
            )
            drive_file = drive_row.scalar_one_or_none()
            if drive_file is None:
                return None, None, []
            return (
                drive_file.video_id,
                entry.llm_label,
                list(entry.spoken_aliases or []),
            )

    def _build_os_client(self):
        """Construct an AsyncOpenSearch client for one STT pipeline call.

        Mirrors ``app/modules/search/client.py::get_opensearch_client``
        (we don't import it because the loose-coupling rule forbids
        cross-module imports; the duplication is ~14 lines of
        configuration).
        """
        from opensearchpy import AsyncOpenSearch

        url = getattr(self.settings, "opensearch_url", "http://localhost:9200")
        is_https = url.startswith("https://")
        return AsyncOpenSearch(
            hosts=[url],
            use_ssl=is_https,
            verify_certs=is_https,
            ssl_show_warn=False,
            timeout=60,
            max_retries=3,
            retry_on_timeout=True,
            pool_maxsize=20,
        )

    # ── helpers (private; tests patch via process_child_fn) ──────────

    async def _load_child_context(
        self, *, child_id: UUID,
    ) -> tuple[ProductScanJob, ProductScanJob, dict[UUID, str]] | None:
        """Read child + parent + catalog (id → label) in one
        read-only session.

        Catalog selection (round-robin) happens in the caller —
        this helper is pure data fetch so the picker call stays in
        one place and the test seam is clean.

        Returns:
            (child, parent, catalog_id_to_label) or None when the
            child / parent is missing or the catalog set is empty.
            ``catalog_id_to_label`` prefers ``user_label`` over
            ``llm_label`` (matches the gallery's display rule).
        """
        async with self.session_factory() as session:
            job_repo = ProductScanJobRepository(session)
            child = await job_repo.get_internal(job_id=child_id)
            if child is None or child.parent_job_id is None:
                return None
            parent = await job_repo.get_internal(job_id=child.parent_job_id)
            if parent is None:
                return None
            catalog_repo = ProductCatalogRepository(session)
            catalog_entries = await catalog_repo.list_active_by_video(
                org_id=parent.org_id, video_id=parent.video_id,
            )
            if not catalog_entries:
                return None
            catalog_label_lookup = {
                c.id: (c.user_label or c.llm_label)
                for c in catalog_entries
            }
            return (child, parent, catalog_label_lookup)

    async def _load_appearances_for_catalog(
        self, *, org_id: UUID, catalog_entry_id: UUID,
    ) -> list[ProductAppearance]:
        async with self.session_factory() as session:
            appearance_repo = ProductAppearanceRepository(session)
            return await appearance_repo.list_active_by_catalog(
                org_id=org_id, catalog_entry_id=catalog_entry_id,
            )

    async def _try_promote_parent_for_child(
        self,
        *,
        child_id: UUID,
        parent_id_hint: UUID | None = None,
    ) -> None:
        """Best-effort eager promotion of the child's parent.

        Called immediately after every child terminal transition
        (success / no-render / failed). When all sibling children
        are terminal, the parent atomically transitions
        ``fanned_out → committed`` — eliminating the "user closed
        wizard before last child finished → parent stuck forever"
        failure mode that the lazy block in
        ``service.py::get_scan_order_status`` was the only safety
        net for.

        Failure to promote is logged but never raised — the lazy
        block stays as belt-and-suspenders. Behind
        ``auto_shorts_product_v2_eager_parent_promotion_enabled``
        for emergency disable.

        Pass ``parent_id_hint`` from sites where parent_id is
        already known (success paths in ``_process_child_payload``
        / ``_process_child_stt``). The catch-all failure paths
        (``_complete_no_render`` / ``_mark_child_failed``) don't
        have parent loaded and pay for one extra ``get_internal``
        lookup; acceptable since the failure path is the cold path.

        See ``.claude/plans/shorts-auto-product-cap-stuck-fix.md``
        (PR 2 of 3).
        """
        if not self.settings.auto_shorts_product_v2_eager_parent_promotion_enabled:
            return
        try:
            async with self.session_factory() as session:
                repo = ProductScanJobRepository(session)
                parent_id = parent_id_hint
                if parent_id is None:
                    child = await repo.get_internal(job_id=child_id)
                    if child is None or child.parent_job_id is None:
                        return
                    parent_id = child.parent_job_id
                promoted = await repo.try_promote_parent_if_all_children_terminal(
                    parent_job_id=parent_id,
                )
                await session.commit()
                if promoted is not None:
                    logger.info(
                        "scan_order_parent_auto_promoted",
                        extra={
                            "parent_id": str(parent_id),
                            "trigger_child_id": str(child_id),
                            "instance_id": self.instance_id,
                        },
                    )
        except Exception:
            logger.exception(
                "parent_promotion_attempt_failed",
                extra={
                    "child_id": str(child_id),
                    "parent_id_hint": (
                        str(parent_id_hint) if parent_id_hint else None
                    ),
                    "instance_id": self.instance_id,
                },
            )

    async def _complete_no_render(
        self, *, child_id: UUID, reason: str,
    ) -> None:
        """Mark the child terminal with no render — analogous to the
        worker's ``_terminate_no_render``. Reaches the same DB shape
        as the happy path (stage=done, render_job_id NULL), so the
        wizard UI surfaces "no render produced for this short"
        without a special-case error path.
        """
        async with self.session_factory() as session:
            repo = ProductScanJobRepository(session)
            completed = await repo.complete_tracking(
                job_id=child_id,
                claimed_by=self.claimed_by,
                cost_delta_usd=Decimal("0"),
                render_job_id=None,
            )
            if completed is None:
                logger.warning(
                    "child_complete_lease_lost_no_render",
                    extra={
                        "child_id": str(child_id),
                        "instance_id": self.instance_id,
                        "reason": reason,
                    },
                )
                return
            await session.commit()
        logger.info(
            "child_runner_no_render",
            extra={
                "child_id": str(child_id),
                "instance_id": self.instance_id,
                "reason": reason,
            },
        )
        # PR 2: eager parent promotion. No parent_id_hint here —
        # _complete_no_render's callers don't all have parent loaded
        # in their scope; helper does the get_internal lookup.
        await self._try_promote_parent_for_child(child_id=child_id)

    async def _create_render_job(
        self,
        *,
        org_id: UUID,
        user_id: UUID,
        os_video_id: str,
        title: str | None,
        composition_spec,
        scan_job_id: UUID,
    ) -> UUID:
        """Construct ``ShortsRenderService`` against a fresh session
        and call ``create_render_job``. Lazy import keeps the runner
        module-level free of cross-module ``shorts_render`` coupling
        (plan §15 carves out direct service use as the runner-side
        equivalent of the internal-router endpoint).
        """
        from app.modules.shorts_render.repository import (
            ShortsRenderJobRepository,
        )
        from app.modules.shorts_render.schemas import RenderJobCreate
        from app.modules.shorts_render.service import ShortsRenderService

        # Widen the render-service dedupe window past our lease horizon.
        # If this replica crashes between create_render_job and
        # complete_tracking, the lease (default 300s) takes that long to
        # expire before another replica re-claims and retries. The
        # service's default 30s window would have closed by then →
        # duplicate render row + orphan S3 output. Adding a 60s buffer
        # covers small clock skew and DB write latency.
        retry_safe_dedupe_seconds = (
            self.settings.auto_shorts_product_v2_child_lease_seconds + 60
        )
        async with self.session_factory() as session:
            render_repo = ShortsRenderJobRepository(session)
            render_service = ShortsRenderService(
                repository=render_repo,
                scene_search=self.scene_search_client,
            )
            response = await render_service.create_render_job(
                org_id=org_id,
                user_id=user_id,
                payload=RenderJobCreate(
                    video_id=os_video_id,
                    title=title,
                    composition=composition_spec,
                ),
                dedupe_within_seconds=retry_safe_dedupe_seconds,
                # Scope dedupe to this scan_job — a crash-retry of
                # the SAME scan collapses (good), but two different
                # scan_jobs producing identical compositions stay
                # distinct (fixes staging 2026-05-06 collision).
                idempotency_key=str(scan_job_id),
            )
            # Commit BEFORE the with-block exits — ``ShortsRenderService``
            # only ``flush()``es the new row, so closing the session
            # without a commit rolls it back. The subsequent
            # ``complete_tracking(render_job_id=…)`` would then reference
            # a non-existent FK and IntegrityError-fail the child path.
            # Mirrors the explicit commit in
            # ``internal_router.enqueue_render_for_scan_job`` (line 709).
            # Codex review caught this — see PR #6 review notes.
            await session.commit()
        return response.id

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
        else:
            # PR 2: eager parent promotion runs ONLY when fail()
            # succeeds (try/except/else). If fail itself failed, the
            # row is in indeterminate state and the lazy promotion in
            # get_scan_order_status will catch up next user poll.
            await self._try_promote_parent_for_child(child_id=child_id)


def _appearance_to_annotated_window(
    appearance: ProductAppearance,
) -> "AnnotatedWindow":
    """Adapt a DB-side :class:`ProductAppearance` into the lib-side
    :class:`AnnotatedWindow` the picker stack consumes.

    Catalog id is dropped on purpose: the runner has already
    narrowed appearances to one catalog before this conversion
    runs, and the vendored lib's ``ScoredWindow`` is catalog-blind
    by design (see ``children/picker.py`` rationale).

    ``peak_confidence`` and ``frame_count`` aren't persisted on
    ``ProductAppearance`` rows (the worker materializes them only
    in-flight), so we approximate:
      * ``peak_confidence`` ← ``avg_confidence`` (best estimate
        without per-frame data; only used by the worker's
        :func:`select_subset` overshoot-trim, not the scorer).
      * ``frame_count`` ← duration_ms / 200ms (5fps SAM2 cadence).
    These approximations don't affect the scorer's composite score
    (which uses ``avg_bbox_area_pct`` + duration-fitness only) but
    keep the dataclass constructor satisfied.
    """
    # Lazy import — keep the runner module-level reference graph
    # small. AnnotatedWindow is only needed in this adapter and in
    # the type annotation above (string-quoted forward ref).
    from app.lib.product_track.alignment import AnnotatedWindow

    duration_ms = appearance.window_end_ms - appearance.window_start_ms
    frame_count_estimate = max(1, duration_ms // 200)
    return AnnotatedWindow(
        scene_id=appearance.scene_id,
        window_start_ms=appearance.window_start_ms,
        window_end_ms=appearance.window_end_ms,
        avg_bbox_area_pct=float(appearance.avg_bbox_area_pct),
        avg_confidence=float(appearance.avg_confidence),
        peak_confidence=float(appearance.avg_confidence),
        frame_count=frame_count_estimate,
        rejected_reason=appearance.rejected_reason,
        has_narration_mention=bool(appearance.has_narration_mention),
        has_ocr_overlap=bool(appearance.has_ocr_overlap),
    )


def create_child_runner(
    *,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    scene_search_client: object,
    instance_id: str | None = None,
) -> ChildRunner:
    """Factory used by ``app.main:lifespan``. Tests construct
    ``ChildRunner`` directly with their own session factory + injected
    ``process_child_fn``.

    ``scene_search_client`` is typed as ``object`` to accept both the
    production ``AsyncOpenSearch`` client and test fakes; the runner
    only forwards it to ``ShortsRenderService`` which will type-check
    against the actual client interface at use time.
    """
    return ChildRunner(
        settings=settings,
        session_factory=session_factory,
        scene_search_client=scene_search_client,
        instance_id=instance_id,
    )
