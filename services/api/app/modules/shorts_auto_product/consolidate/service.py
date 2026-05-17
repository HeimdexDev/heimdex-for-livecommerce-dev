"""Orchestrator for the post-enumeration catalog consolidation.

End-to-end:

1. Wait for the parallel STT enumeration path to land its rows.
   Fixed grace sleep keyed off ``consolidate_grace_s`` (defaults to
   STT timeout + 15s headroom) — no DB coordination column needed.
2. Idempotency check: skip when ``rejected_reason`` already carries a
   consolidation marker on any row for this video. Both vision retries
   and accidental double-fires of the scheduler converge cleanly.
3. Load the active catalog for the video. Skip on ``len <= 1`` — a
   single-row catalog has nothing to merge and the LLM call wastes
   money.
4. Call gpt-4o with the strict-JSON consolidation prompt. Reject the
   response if any entry_id is hallucinated or the exactly-once
   invariant is violated.
5. Apply the result via :meth:`ProductCatalogRepository.apply_consolidation`:
   canonical rows get UPDATEd labels + aliases; duplicate rows get
   soft-rejected with reason ``duplicate_of:<canonical_uuid>``;
   non-sellable rows get soft-rejected with reason
   ``non_sellable:<category>``. Existing ``list_active_by_video``
   filters out ``rejected_at IS NOT NULL`` so the gallery shrinks
   immediately.

Fire-and-forget from the vision ``/internal/products/.../complete``
callback. Vision still owns the ``ProductScanJob`` lifecycle — this
orchestrator's only side effect is mutating catalog rows. If the
consolidation path fails entirely, the wizard still works (raw
catalog is visible, just with the un-merged duplicates).

Loose-coupling: imports ONLY from ``openai``, :mod:`app.config`,
:mod:`app.db.base`, :mod:`app.modules.shorts_auto_product.models`,
own-module symbols, and the catalog repository. No cross-imports
from other ``app.modules.*``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.shorts_auto_product.consolidate.errors import (
    ConsolidationError,
    ConsolidationLLMError,
    ConsolidationValidationError,
)
from app.modules.shorts_auto_product.consolidate.llm_consolidator import (
    CatalogConsolidator,
    CatalogConsolidatorInput,
    ConsolidationResult,
)
from app.modules.shorts_auto_product.repositories.catalog import (
    ProductCatalogRepository,
)

logger = logging.getLogger(__name__)


# Strong-ref set for fire-and-forget background tasks. Mirrors the
# pattern in ``enumerate_stt.service`` — without this set the Task
# returned by ``asyncio.create_task`` can be garbage-collected mid-run.
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


async def run_consolidation(
    *,
    session: AsyncSession,
    openai_client: Any,
    org_id: UUID,
    video_db_id: UUID,
    consolidator: CatalogConsolidator | None = None,
    prompt_version: str = "v1.0",
) -> tuple[int, int, int]:
    """Run the consolidation pipeline end-to-end.

    Args:
        session: Async SQLAlchemy session. The caller manages the
            commit boundary — this function only flushes (via the
            repository).
        openai_client: ``AsyncOpenAI``. Can be a fake / mock in tests.
        org_id: Tenant scope.
        video_db_id: ``drive_files.id`` UUID for the video being
            consolidated.
        consolidator: Inject a pre-configured
            :class:`CatalogConsolidator` to share connection pools
            across calls. When ``None``, a per-call instance is
            constructed using ``openai_client`` and ``prompt_version``.
        prompt_version: Stamped onto canonical rows'
            ``aliases_prompt_version`` so the backfill CLI does not
            re-process them, and bumping it forces a fresh
            consolidation pass on the next scan.

    Returns ``(canonicals_updated, duplicates_rejected,
    non_sellables_rejected)`` for observability. ``(0, 0, 0)`` when the
    pipeline short-circuited (trivial catalog, already consolidated,
    LLM failure).

    Never raises — consolidation is best-effort. All failures are
    logged and the function returns ``(0, 0, 0)`` so the caller does
    not have to swallow exceptions itself.
    """
    catalog_repo = ProductCatalogRepository(session)

    # ---- 1. Idempotency ----
    try:
        already = await catalog_repo.has_consolidation_markers(
            org_id=org_id, video_id=video_db_id,
        )
    except Exception as e:  # noqa: BLE001 — never raise
        logger.warning(
            "consolidate_marker_check_failed",
            extra={
                "video_db_id": str(video_db_id),
                "org_id": str(org_id),
                "error": str(e)[:300],
            },
        )
        return (0, 0, 0)
    if already:
        logger.info(
            "consolidate_skipped_already_done",
            extra={
                "video_db_id": str(video_db_id),
                "org_id": str(org_id),
            },
        )
        return (0, 0, 0)

    # ---- 2. Load catalog ----
    try:
        entries = await catalog_repo.list_active_by_video(
            org_id=org_id, video_id=video_db_id,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "consolidate_load_failed",
            extra={
                "video_db_id": str(video_db_id),
                "org_id": str(org_id),
                "error": str(e)[:300],
            },
        )
        return (0, 0, 0)
    if len(entries) <= 1:
        logger.info(
            "consolidate_skipped_trivial",
            extra={
                "video_db_id": str(video_db_id),
                "org_id": str(org_id),
                "entry_count": len(entries),
            },
        )
        return (0, 0, 0)

    # ---- 3. LLM call ----
    consolidator = consolidator or CatalogConsolidator(
        openai_client=openai_client,
        prompt_version=prompt_version,
    )
    inputs = [
        CatalogConsolidatorInput(
            entry_id=e.id,
            llm_label=e.llm_label,
            spoken_aliases=list(e.spoken_aliases or []),
            source=e.enumeration_source,
            confidence=float(e.enumeration_confidence),
            example_quote=e.example_quote,
        )
        for e in entries
    ]
    try:
        result = await consolidator.consolidate(entries=inputs)
    except ConsolidationLLMError as e:
        logger.warning(
            "consolidate_llm_failed",
            extra={
                "video_db_id": str(video_db_id),
                "org_id": str(org_id),
                "entry_count": len(entries),
                "error": str(e)[:300],
            },
        )
        return (0, 0, 0)
    except ConsolidationValidationError as e:
        logger.warning(
            "consolidate_validation_failed",
            extra={
                "video_db_id": str(video_db_id),
                "org_id": str(org_id),
                "entry_count": len(entries),
                "error": str(e)[:300],
            },
        )
        return (0, 0, 0)
    except ConsolidationError as e:
        logger.warning(
            "consolidate_unexpected_pipeline_error",
            extra={
                "video_db_id": str(video_db_id),
                "org_id": str(org_id),
                "error": str(e)[:300],
            },
        )
        return (0, 0, 0)
    except Exception as e:  # noqa: BLE001
        logger.exception(
            "consolidate_unexpected_failure",
            extra={
                "video_db_id": str(video_db_id),
                "org_id": str(org_id),
                "error": str(e)[:300],
            },
        )
        return (0, 0, 0)

    # ---- 4. Translate result to repo payloads ----
    canonical_updates, duplicate_rejections, non_sellable_rejections = (
        _result_to_repo_payloads(result)
    )
    if (
        not canonical_updates
        and not duplicate_rejections
        and not non_sellable_rejections
    ):
        logger.info(
            "consolidate_no_changes",
            extra={
                "video_db_id": str(video_db_id),
                "org_id": str(org_id),
                "entry_count": len(entries),
                "cost_usd": result.cost_usd,
                "latency_ms": result.latency_ms,
            },
        )
        return (0, 0, 0)

    # ---- 5. Apply ----
    try:
        counts = await catalog_repo.apply_consolidation(
            org_id=org_id,
            video_id=video_db_id,
            canonical_updates=canonical_updates,
            duplicate_rejections=duplicate_rejections,
            non_sellable_rejections=non_sellable_rejections,
            prompt_version=result.prompt_version,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception(
            "consolidate_apply_failed",
            extra={
                "video_db_id": str(video_db_id),
                "org_id": str(org_id),
                "error": str(e)[:300],
            },
        )
        return (0, 0, 0)

    canonicals_updated, duplicates_rejected, non_sellables_rejected = counts
    logger.info(
        "consolidate_completed",
        extra={
            "video_db_id": str(video_db_id),
            "org_id": str(org_id),
            "input_count": len(entries),
            "canonicals_updated": canonicals_updated,
            "duplicates_rejected": duplicates_rejected,
            "non_sellables_rejected": non_sellables_rejected,
            "cost_usd": result.cost_usd,
            "latency_ms": result.latency_ms,
            "model": result.model,
            "prompt_version": result.prompt_version,
        },
    )
    return counts


# ---------- pure helpers ----------


def _result_to_repo_payloads(
    result: ConsolidationResult,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Split the LLM result into the three repo-shaped payload lists.

    A group with no members and a canonical_label / canonical_aliases
    identical to the existing row's fields would still trigger an
    UPDATE in the repository — that's fine: the rowcount is just an
    observability number, the no-op write is cheap, and we don't want
    to re-read each row here to compare. The repository checks
    ``rejected_at IS NULL`` so canonical updates against an
    already-rejected row become no-ops.
    """
    canonical_updates: list[dict[str, Any]] = []
    duplicate_rejections: list[dict[str, Any]] = []
    non_sellable_rejections: list[dict[str, Any]] = []

    for group in result.groups:
        canonical_updates.append({
            "entry_id": group.canonical_entry_id,
            "llm_label": group.canonical_label,
            "spoken_aliases": list(group.canonical_aliases),
        })
        for member_id in group.member_entry_ids:
            duplicate_rejections.append({
                "entry_id": member_id,
                "canonical_entry_id": group.canonical_entry_id,
            })

    for rejection in result.rejections:
        non_sellable_rejections.append({
            "entry_id": rejection.entry_id,
            "category": rejection.category,
        })

    return canonical_updates, duplicate_rejections, non_sellable_rejections


def schedule_consolidation_task(
    *,
    settings: Any,
    org_id: UUID,
    video_db_id: UUID,
) -> None:
    """Fire-and-forget scheduler. Safe to call from any async handler.

    Called from the vision ``/internal/products/.../complete`` callback
    after the catalog rows have been persisted. The task sleeps
    ``consolidate_grace_s`` seconds before doing anything so the
    parallel STT enumeration has a chance to land its rows; after
    the sleep it constructs its OWN session + OpenAI client and runs
    :func:`run_consolidation`.

    No-op when:
      - ``auto_shorts_product_v2_consolidate_enabled`` is False
      - ``openai_api_key`` is empty (the LLM call would fail anyway)

    Mirrors :func:`enumerate_stt.service.schedule_stt_enumeration_task`.
    The grace sleep is the only difference; STT does not wait because
    nothing else has to land before it can run.
    """
    if not getattr(settings, "auto_shorts_product_v2_consolidate_enabled", False):
        return
    api_key = getattr(settings, "openai_api_key", "") or ""
    if not api_key:
        logger.info(
            "consolidate_skipped_no_api_key",
            extra={
                "video_db_id": str(video_db_id),
                "org_id": str(org_id),
            },
        )
        return

    grace_s = float(getattr(
        settings, "auto_shorts_product_v2_consolidate_grace_s", 105.0,
    ))
    model = getattr(
        settings, "auto_shorts_product_v2_consolidate_model", "gpt-4o",
    )
    timeout_s = float(getattr(
        settings, "auto_shorts_product_v2_consolidate_timeout_s", 120.0,
    ))
    prompt_version = getattr(
        settings,
        "auto_shorts_product_v2_consolidate_prompt_version",
        "v1.0",
    )

    async def _runner() -> None:
        try:
            # Grace sleep — let STT enumeration finish writing its rows
            # so consolidate sees the merged candidate set. Best-effort
            # only: if STT crashes silently, consolidate still runs on
            # whatever's in the catalog at this point.
            if grace_s > 0:
                await asyncio.sleep(grace_s)

            openai_client = _build_openai_client(api_key=api_key)
            try:
                from app.db.base import get_async_session_factory
                session_factory = get_async_session_factory()
                async with session_factory() as session:
                    consolidator = CatalogConsolidator(
                        openai_client=openai_client,
                        model=model,
                        timeout_s=timeout_s,
                        prompt_version=prompt_version,
                    )
                    counts = await run_consolidation(
                        session=session,
                        openai_client=openai_client,
                        org_id=org_id,
                        video_db_id=video_db_id,
                        consolidator=consolidator,
                        prompt_version=prompt_version,
                    )
                    if any(counts):
                        await session.commit()
            finally:
                # Best-effort cleanup — the OpenAI client holds a
                # connection pool we should release even on failure.
                try:
                    if hasattr(openai_client, "close"):
                        maybe_coro = openai_client.close()
                        if asyncio.iscoroutine(maybe_coro):
                            await maybe_coro
                except Exception:
                    pass
        except Exception:  # noqa: BLE001
            logger.exception(
                "consolidate_background_runner_failed",
                extra={
                    "video_db_id": str(video_db_id),
                    "org_id": str(org_id),
                },
            )

    task = asyncio.create_task(_runner())
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


def _build_openai_client(*, api_key: str):
    """Construct an AsyncOpenAI client. Per-task instantiation; the
    pool is short-lived but per-task latency is dominated by the LLM
    round-trip, not the client setup.
    """
    from openai import AsyncOpenAI

    return AsyncOpenAI(api_key=api_key)


__all__ = [
    "run_consolidation",
    "schedule_consolidation_task",
]
