"""Shared alias backfill core. Used by:
  - app.cli.backfill_spoken_aliases (whole org)
  - aliases.auto_hook (single video, post-enumeration)
Single source of truth for selection + generate + persist.
"""
from __future__ import annotations

import logging
from uuid import UUID

logger = logging.getLogger(__name__)


async def backfill_aliases_for_video(
    *, session_factory, org_id: UUID | None, video_db_id: UUID | None, settings
) -> int:
    """Select this video's catalog entries needing aliases
    (missing or prompt_version != current), generate, persist.
    Budget circuit-breaker. Never raises. Returns count processed.
    """
    from openai import AsyncOpenAI

    from app.storage.s3 import S3Client
    from app.modules.shorts_auto_product.aliases import (
        AliasGenerationBudgetExceeded,
        AliasGenerationError,
        AliasGenerationRetryable,
        AliasGenerationTerminal,
        AliasGenerator,
    )
    from app.modules.shorts_auto_product.aliases.generator import (
        _DEFAULT_MODEL,
    )
    from app.modules.shorts_auto_product.repositories.catalog import (
        ProductCatalogRepository,
    )

    openai_client = AsyncOpenAI(
        api_key=settings.openai_api_key, timeout=15.0,
    )
    s3_client = S3Client(bucket=settings.drive_s3_bucket)
    generator = AliasGenerator(
        openai_client=openai_client, s3_client=s3_client,
        model=_DEFAULT_MODEL,
    )

    async with session_factory() as session:
        repo = ProductCatalogRepository(session)
        entries = await repo.find_entries_needing_aliases(
            current_prompt_version=generator.prompt_version,
            org_id=org_id,
            video_id=video_db_id,
            limit=1000,
        )
    if not entries:
        return 0

    budget = float(getattr(
        settings,
        "auto_shorts_product_v2_alias_daily_budget_usd",
        5.0,
    ))
    total_cost = 0.0
    processed = 0
    for entry in entries:
        if total_cost >= budget:
            logger.warning(
                "alias_backfill_core_budget_reached",
                extra={"spent_usd": total_cost, "budget": budget},
            )
            break
        try:
            result = await generator.generate(
                canonical_crop_s3_key=entry.canonical_crop_s3_key,
                llm_label=entry.llm_label,
            )
        except AliasGenerationBudgetExceeded:
            break
        except (
            AliasGenerationTerminal,
            AliasGenerationRetryable,
            AliasGenerationError,
        ) as e:
            logger.warning(
                "alias_backfill_core_entry_failed",
                extra={"entry_id": str(entry.id), "error": str(e)[:200]},
            )
            continue

        async with session_factory() as session:
            repo = ProductCatalogRepository(session)
            await repo.update_aliases(
                entry_id=entry.id,
                aliases=result.aliases,
                prompt_version=result.prompt_version,
            )
            await session.commit()
        total_cost += result.cost_usd
        processed += 1
    return processed