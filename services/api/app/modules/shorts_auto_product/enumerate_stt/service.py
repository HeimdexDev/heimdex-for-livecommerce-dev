"""Orchestrator for the STT-first enumeration pipeline.

End-to-end:
1. Load the video's transcript from OpenSearch (one query, ordered).
2. Call gpt-4o-mini with strict-JSON schema for product enumeration.
3. Dedupe against existing vision-source catalog rows for the same
   video — STT entries that overlap a vision row's
   ``llm_label`` or ``spoken_aliases`` are dropped (vision wins
   because it has a canonical crop the wizard can render).
4. Insert the survivors as new catalog rows with
   ``enumeration_source='stt'``.

Fire-and-forget from ``service.py::enqueue_scan``. Vision still owns
the ``ProductScanJob`` lifecycle transition to ``enumeration_done``;
this orchestrator's only side effect is writing additional catalog
rows. If the STT path fails entirely, the wizard still works (vision
populates the catalog on its own schedule).

Loose-coupling: this module imports ONLY from ``opensearchpy``,
``openai``, :mod:`heimdex_media_contracts.product`,
:mod:`app.config`, :mod:`app.modules.shorts_auto_product.models`
and the catalog repository, and own-module symbols. No cross-imports
from other ``app.modules.*``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID, uuid4

from heimdex_media_contracts.product import (
    TRANSCRIPT_ENUMERATION_PROMPT_VERSION,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.shorts_auto_product.enumerate_stt.errors import (
    EnumerationLLMError,
    STTEnumerationError,
    TranscriptUnavailableError,
)
from app.modules.shorts_auto_product.enumerate_stt.llm_enumerator import (
    TranscriptEnumerator,
)
from app.modules.shorts_auto_product.enumerate_stt.transcript_loader import (
    load_transcript,
)
from app.modules.shorts_auto_product.models import ProductCatalogEntry
from app.modules.shorts_auto_product.repositories.catalog import (
    ProductCatalogRepository,
)

logger = logging.getLogger(__name__)


# Strong-ref set for fire-and-forget background tasks.
# ``asyncio.create_task`` returns a Task that gets garbage-collected
# the moment its caller stops referencing it; without this set the
# task can be collected mid-run. Same pattern as image_caption.service.
# Cleared via the done-callback in ``schedule_stt_enumeration_task``.
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


# Algorithm version for STT-source rows. Distinct from
# ``TranscriptEnumerationPrompt.VERSION`` (the prompt version, which
# goes in ``enumeration_prompt_version``) — this is the pipeline
# version that captures non-prompt changes (e.g., the dedup logic
# in this module). Bump on logic changes that should re-trigger the
# "newer scan available" UX banner. Vision rows use ``"v1.0"``;
# the ``"stt-"`` prefix makes provenance unambiguous in DB queries.
STT_ENUMERATION_VERSION = "stt-v1.0"


async def run_stt_enumeration(
    *,
    session: AsyncSession,
    os_client: Any,
    openai_client: Any,
    org_id: UUID,
    video_db_id: UUID,
    video_drive_id: str,
    index_alias: str = "heimdex_scenes",
    max_transcript_tokens: int = 80000,
    enumerator: TranscriptEnumerator | None = None,
) -> int:
    """Run the STT-first enumeration pipeline end-to-end.

    Args:
        session: Async SQLAlchemy session for the catalog write. The
            caller manages commit boundaries — this function only
            issues ``flush()`` (via the repository), giving the caller
            transactional control.
        os_client: ``AsyncOpenSearch`` for the transcript fetch.
        openai_client: ``AsyncOpenAI`` for the enumeration call. Can
            be a fake / mock in tests.
        org_id: Tenant scope.
        video_db_id: ``drive_files.id`` UUID — what the catalog row's
            ``video_id`` foreign key references.
        video_drive_id: ``gd_<hash>`` string — what OpenSearch indexes
            scenes against. Both IDs are needed because the two
            stores key on different identifiers.
        index_alias: OS alias to query.
        max_transcript_tokens: Truncation guardrail. Char-cap derived
            inside :func:`load_transcript`.
        enumerator: Inject a pre-configured
            :class:`TranscriptEnumerator` to share connection pools
            across calls. When ``None``, a per-call instance is
            constructed.

    Returns:
        Number of catalog rows inserted (0 when STT was unavailable,
        the LLM failed, or every product was deduped against an
        existing vision row).

    Never raises — STT enumeration is best-effort augmentation. All
    failures are logged at the appropriate level and the function
    returns 0 so the caller's fan-out logic doesn't have to swallow
    exceptions itself.
    """
    enumerator = enumerator or TranscriptEnumerator(openai_client=openai_client)

    # ---- 1. Load transcript ----
    try:
        transcript, scene_count = await load_transcript(
            os_client=os_client,
            index_alias=index_alias,
            org_id=org_id,
            video_id=video_drive_id,
            max_tokens=max_transcript_tokens,
        )
    except TranscriptUnavailableError:
        # Expected for some videos — silent enrichment running, or
        # genuinely-no-spoken-content videos. Vision still runs.
        return 0
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "stt_enum_transcript_load_failed",
            extra={
                "video_id": video_drive_id,
                "org_id": str(org_id),
                "error": str(e)[:300],
            },
        )
        return 0

    # ---- 2. LLM enumeration ----
    try:
        result = await enumerator.enumerate(transcript=transcript)
    except EnumerationLLMError as e:
        logger.warning(
            "stt_enum_llm_failed",
            extra={
                "video_id": video_drive_id,
                "org_id": str(org_id),
                "scene_count": scene_count,
                "error": str(e)[:300],
            },
        )
        return 0
    except Exception as e:  # noqa: BLE001
        logger.exception(
            "stt_enum_unexpected_failure",
            extra={
                "video_id": video_drive_id,
                "org_id": str(org_id),
                "error": str(e)[:300],
            },
        )
        return 0

    if not result.products:
        logger.info(
            "stt_enum_zero_products",
            extra={
                "video_id": video_drive_id,
                "org_id": str(org_id),
                "scene_count": scene_count,
                "cost_usd": result.cost_usd,
                "latency_ms": result.latency_ms,
                "dropped_count": result.dropped_count,
            },
        )
        return 0

    # ---- 3. Dedupe against existing vision rows ----
    catalog_repo = ProductCatalogRepository(session)
    existing = await catalog_repo.list_active_by_video(
        org_id=org_id, video_id=video_db_id,
    )
    existing_terms = _build_dedup_term_set(existing)
    survivors = [
        p for p in result.products
        if not _has_term_overlap(p, existing_terms)
    ]
    if not survivors:
        logger.info(
            "stt_enum_all_deduped",
            extra={
                "video_id": video_drive_id,
                "org_id": str(org_id),
                "candidate_count": len(result.products),
                "existing_count": len(existing),
            },
        )
        return 0

    # ---- 4. Insert STT-source rows ----
    rows = [
        _to_catalog_row(
            product=p,
            org_id=org_id,
            video_id=video_db_id,
            prompt_version=result.prompt_version,
        )
        for p in survivors
    ]
    inserted = await catalog_repo.bulk_insert(entries=rows)

    logger.info(
        "stt_enum_completed",
        extra={
            "video_id": video_drive_id,
            "org_id": str(org_id),
            "scene_count": scene_count,
            "candidate_count": len(result.products),
            "inserted_count": len(inserted),
            "deduped_count": len(result.products) - len(survivors),
            "dropped_quote_fidelity": result.dropped_count,
            "cost_usd": result.cost_usd,
            "latency_ms": result.latency_ms,
            "model": result.model,
            "prompt_version": result.prompt_version,
        },
    )
    return len(inserted)


# ---------- pure helpers (testable in isolation) ----------


def _normalize_term(text: str) -> str:
    """Casefold + strip — the dedup key for label/alias overlap.

    Korean is naturally case-insensitive but we still casefold for
    Latin-alphabet brand names that round-trip through the LLM
    inconsistently (``"Dalsim"`` vs ``"dalsim"``).
    """
    return text.casefold().strip()


def _build_dedup_term_set(
    existing: list[ProductCatalogEntry],
) -> set[str]:
    """Build the set of normalized labels + aliases across all
    active vision-source (and prior STT-source) rows.

    Including all sources is intentional — if vision and STT both
    discover the same product, the second-running path drops its
    duplicate. Re-running enumeration on a video should be
    idempotent: STT entries from a previous scan are still in the
    catalog and a fresh STT run sees them via this set.
    """
    terms: set[str] = set()
    for entry in existing:
        if entry.llm_label:
            terms.add(_normalize_term(entry.llm_label))
        for alias in (entry.spoken_aliases or []):
            if alias:
                terms.add(_normalize_term(alias))
    return terms


def _has_term_overlap(product: Any, existing_terms: set[str]) -> bool:
    """Return True if the product's label or any alias matches an
    existing term. Pure substring identity — no fuzzy matching today.

    The product is :class:`TranscriptEnumeratedProduct` from the
    contracts package; we accept Any to avoid the import dance for
    test mocks.
    """
    if _normalize_term(product.llm_label) in existing_terms:
        return True
    for alias in (product.spoken_aliases or []):
        if _normalize_term(alias) in existing_terms:
            return True
    return False


def _to_catalog_row(
    *,
    product: Any,
    org_id: UUID,
    video_id: UUID,
    prompt_version: str,
) -> dict[str, Any]:
    """Convert a :class:`TranscriptEnumeratedProduct` to the dict
    shape :meth:`ProductCatalogRepository.bulk_insert` expects.

    STT-source rows leave every vision-only field NULL:
        - canonical_crop_s3_key
        - canonical_video_id
        - canonical_frame_idx
        - canonical_bbox_{x,y,w,h}
        - siglip2_embedding (already nullable pre-055)
        - prominence_score

    Migration 055 dropped NOT NULL on the canonical_* + prominence
    columns so this insert succeeds. ``enumeration_confidence``
    stays NOT NULL — STT path also has a confidence score.
    """
    return {
        "id": uuid4(),
        "org_id": org_id,
        "video_id": video_id,
        # Vision-only fields — explicit NULL keeps the wizard's
        # source-aware rendering clean (cropless cards show the
        # generic icon).
        "canonical_crop_s3_key": None,
        "canonical_video_id": None,
        "canonical_frame_idx": None,
        "canonical_bbox_x": None,
        "canonical_bbox_y": None,
        "canonical_bbox_w": None,
        "canonical_bbox_h": None,
        "siglip2_embedding": None,
        # Both paths emit these.
        "llm_label": product.llm_label,
        "user_label": None,
        "enumeration_confidence": float(product.confidence),
        "prominence_score": None,
        "enumeration_version": STT_ENUMERATION_VERSION,
        "enumeration_prompt_version": prompt_version,
        # v0.15.0 columns — STT entries get aliases inline (no
        # second-pass alias generation needed) so we mark them as
        # already generated under the same prompt_version. The
        # backfill CLI's selection query won't pick these up,
        # which is the correct behavior.
        "spoken_aliases": list(product.spoken_aliases),
        "aliases_generated_at": _now_utc(),
        "aliases_prompt_version": prompt_version,
        # v0.16.0 columns — the new fields this PR depends on.
        "enumeration_source": "stt",
        "first_mention_ms": int(product.first_mention_ms),
        "example_quote": product.example_quote,
        "rejected_at": None,
        "rejected_reason": None,
    }


def _now_utc():
    """Wallclock UTC. Indirected so tests can patch deterministically."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def schedule_stt_enumeration_task(
    *,
    settings: Any,
    org_id: UUID,
    video_db_id: UUID,
    video_drive_id: str | None = None,
) -> None:
    """Fire-and-forget scheduler. Safe to call from any async handler.

    The scan endpoint calls this AFTER the SQS publish to the vision
    worker; STT runs on the same event loop but outside the request
    lifecycle. Failures do not affect the HTTP response.

    Args:
        video_db_id: ``drive_files.id`` UUID — required.
        video_drive_id: ``gd_<hash>`` string. When ``None``, the
            background task resolves it from the ``drive_files`` row
            inside its own session. Pass it explicitly when the caller
            already has it loaded to save a query.

    No-op when:
      - ``auto_shorts_product_v2_stt_enum_enabled`` is False
      - ``openai_api_key`` is empty (the LLM call would fail anyway)

    The task constructs its OWN session, OS client, and OpenAI client
    — the request session must NOT be shared with a task that outlives
    the request (it'd be closed mid-write).

    Mirrors :func:`image_caption.service.schedule_image_caption_task`.
    """
    if not getattr(settings, "auto_shorts_product_v2_stt_enum_enabled", False):
        return
    api_key = getattr(settings, "openai_api_key", "") or ""
    if not api_key:
        logger.info(
            "stt_enum_skipped_no_api_key",
            extra={
                "video_id": video_drive_id,
                "org_id": str(org_id),
            },
        )
        return

    async def _runner() -> None:
        try:
            os_client = _build_os_client(settings)
            openai_client = _build_openai_client(api_key=api_key)
            try:
                from app.db.base import get_async_session_factory
                session_factory = get_async_session_factory()
                async with session_factory() as session:
                    # Resolve the gd_xxx drive_id string from the
                    # drive_files row when the caller didn't pre-resolve.
                    resolved_drive_id = video_drive_id or await _resolve_drive_id(
                        session=session, video_db_id=video_db_id,
                    )
                    if resolved_drive_id is None:
                        logger.warning(
                            "stt_enum_video_not_found",
                            extra={
                                "video_db_id": str(video_db_id),
                                "org_id": str(org_id),
                            },
                        )
                        return

                    enumerator = TranscriptEnumerator(
                        openai_client=openai_client,
                        model=getattr(
                            settings,
                            "auto_shorts_product_v2_stt_enum_model",
                            "gpt-4o-mini",
                        ),
                        timeout_s=float(getattr(
                            settings,
                            "auto_shorts_product_v2_stt_enum_timeout_s",
                            90.0,
                        )),
                    )
                    inserted = await run_stt_enumeration(
                        session=session,
                        os_client=os_client,
                        openai_client=openai_client,
                        org_id=org_id,
                        video_db_id=video_db_id,
                        video_drive_id=resolved_drive_id,
                        max_transcript_tokens=int(getattr(
                            settings,
                            "auto_shorts_product_v2_stt_enum_max_transcript_tokens",
                            80000,
                        )),
                        enumerator=enumerator,
                    )
                    if inserted:
                        await session.commit()
                        from app.modules.shorts_auto_product.aliases.auto_hook import (
                            schedule_alias_generation,
                        )
                        schedule_alias_generation(
                            org_id=org_id,
                            video_db_id=video_db_id,
                            settings=settings,
                        )
            finally:
                # Best-effort cleanup — the OS / OpenAI clients hold
                # connection pools we should release even on failure.
                try:
                    if hasattr(os_client, "close"):
                        await os_client.close()
                except Exception:
                    pass
                try:
                    if hasattr(openai_client, "close"):
                        maybe_coro = openai_client.close()
                        if asyncio.iscoroutine(maybe_coro):
                            await maybe_coro
                except Exception:
                    pass
        except Exception:  # noqa: BLE001
            logger.exception(
                "stt_enum_background_runner_failed",
                extra={
                    "video_id": video_drive_id,
                    "org_id": str(org_id),
                },
            )

    task = asyncio.create_task(_runner())
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


async def _resolve_drive_id(
    *,
    session: AsyncSession,
    video_db_id: UUID,
) -> str | None:
    """Look up ``drive_files.video_id`` (the ``gd_<hash>`` string) by id.

    Lazy local import of ``DriveFile`` mirrors the runner's pattern —
    keeps the drive module out of this module's import graph until
    the STT path is actually taken. Loose-coupling rule allows lazy
    cross-module imports for resource lookups; module-level
    cross-imports are what's forbidden.
    """
    from sqlalchemy import select as _select

    from app.modules.drive.models import DriveFile

    result = await session.execute(
        _select(DriveFile.video_id).where(DriveFile.id == video_db_id),
    )
    return result.scalar_one_or_none()


def _build_os_client(settings: Any):
    """Construct an AsyncOpenSearch client for one fan-out call.

    Mirrors ``children/runner.py::_build_os_client`` — the duplication
    is ~14 lines and avoids cross-module imports per the loose-
    coupling rule. Safe to instantiate per-call (the task pool inside
    AsyncOpenSearch handles short-lived clients gracefully).
    """
    from opensearchpy import AsyncOpenSearch

    url = getattr(settings, "opensearch_url", "http://localhost:9200")
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


def _build_openai_client(*, api_key: str):
    """Construct an AsyncOpenAI client. Per-task instantiation; the
    pool is short-lived but the per-task latency is dominated by the
    LLM round-trip, not the client setup.
    """
    from openai import AsyncOpenAI

    return AsyncOpenAI(api_key=api_key)


__all__ = [
    "STT_ENUMERATION_VERSION",
    "STTEnumerationError",
    "run_stt_enumeration",
    "schedule_stt_enumeration_task",
]


# Re-export for completeness — TRANSCRIPT_ENUMERATION_PROMPT_VERSION
# is used by callers that wire env defaults around this module.
_PROMPT_VERSION_REEXPORT = TRANSCRIPT_ENUMERATION_PROMPT_VERSION
