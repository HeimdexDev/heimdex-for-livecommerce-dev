"""Backfill spoken-form aliases for product_catalog_entries.

Per ``.claude/plans/shorts-auto-product-stt-pivot.md`` PR 1b. The
auto-shorts product mode v2 STT-pivot replaces SAM2 visual tracking
with mention extraction over OpenSearch ``transcript_raw`` /
``scene_caption``. Per validation on ``gd_05e7f957502e86cf`` (the
handoff video, 9 catalog entries), 3 of 9 catalog ``llm_label``
strings do not substring-match the host's spoken Korean — without an
alias layer ~33% of catalog entries return zero spoken mentions.

This CLI fills the ``spoken_aliases`` column for catalog entries that
either have never been processed (``aliases_generated_at IS NULL``) OR
were processed under an older prompt version
(``aliases_prompt_version != current_version``). Existing entries are
unchanged. Each entry generates ~$0.0002 of OpenAI spend at
gpt-4o-mini pricing; a 50-entry org-wide run is ~$0.01.

Usage:

    docker compose exec -T api python -m app.cli.backfill_spoken_aliases \\
        --org devorg --dry-run

    docker compose exec -T api python -m app.cli.backfill_spoken_aliases \\
        --org devorg --max-cost-usd 0.05

    docker compose exec -T api python -m app.cli.backfill_spoken_aliases \\
        --org devorg --video gd_05e7f957502e86cf

The CLI is idempotent: re-running with no-op selection skips already
generated rows. If a generation attempt fails terminally for one
entry (e.g., S3 NoSuchKey, JSON validation refused), the CLI logs +
skips and continues; the row stays at ``aliases_generated_at IS NULL``
so a future re-run can retry once the underlying issue is fixed
(e.g., the S3 key is restored).

Selection ordering is by ``created_at ASC`` to make backfills
resumable: a kill mid-batch leaves the already-aliased rows
permanently out of the selection, and the next run picks up where
the previous left off.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from typing import Any
from uuid import UUID

from sqlalchemy import select

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill spoken_aliases on product_catalog_entries",
    )
    parser.add_argument(
        "--org", type=str, default=None,
        help="Org slug or UUID. Omit to process all orgs.",
    )
    parser.add_argument(
        "--video", type=str, default=None,
        help=(
            "Filter to one drive video_id (e.g. gd_05e7f957502e86cf). "
            "Resolved against drive_files.video_id; the underlying "
            "DB FK is the drive_files.id UUID."
        ),
    )
    parser.add_argument(
        "--limit", type=int, default=1000,
        help="Cap on entries fetched per CLI run. Default 1000.",
    )
    parser.add_argument(
        "--max-cost-usd", type=float, default=5.0,
        help=(
            "Pre-flight ceiling on total estimated spend across the "
            "batch. CLI stops if the running total would exceed this. "
            "Default $5 — well above the ~$0.01 / 50 entries baseline."
        ),
    )
    parser.add_argument(
        "--model", type=str, default=_DEFAULT_MODEL,
        help=f"OpenAI model id. Default {_DEFAULT_MODEL}.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help=(
            "Select + report what WOULD be processed; do NOT call "
            "OpenAI or write to the DB."
        ),
    )
    return parser


async def _resolve_org_id(session: Any, org_arg: str | None) -> UUID | None:
    """Org slug or UUID → org_id UUID, or None if --org omitted."""
    if not org_arg:
        return None
    from app.modules.orgs.models import Org  # local to avoid cycles

    try:
        org_uuid = UUID(org_arg)
        result = await session.execute(select(Org).where(Org.id == org_uuid))
    except ValueError:
        result = await session.execute(select(Org).where(Org.slug == org_arg))
    org = result.scalar_one_or_none()
    if org is None:
        raise SystemExit(f"Org not found: {org_arg}")
    return org.id


async def _resolve_video_id(session: Any, video_arg: str | None) -> UUID | None:
    """drive_files.video_id (e.g. gd_X) → drive_files.id UUID."""
    if not video_arg:
        return None
    from sqlalchemy import text as sql_text

    result = await session.execute(
        sql_text("SELECT id FROM drive_files WHERE video_id = :v LIMIT 1"),
        {"v": video_arg},
    )
    row = result.first()
    if row is None:
        raise SystemExit(f"Video not found: {video_arg}")
    return row[0]


async def _run(args: argparse.Namespace) -> int:
    """Returns exit code: 0 = success, 2 = budget exceeded, 1 = errors."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.config import get_settings
    from app.db.base import get_async_engine
    from app.storage.s3 import S3Client

    settings = get_settings()
    if not getattr(settings, "openai_api_key", None):
        logger.error(
            "OPENAI_API_KEY is not set — cannot run alias generation. "
            "Set it in the api container env (same key used by "
            "image_caption / video_summary / auto_shorts_llm)."
        )
        return 1

    engine = get_async_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        org_id = await _resolve_org_id(session, args.org)
        video_uuid = await _resolve_video_id(session, args.video)

    # AsyncOpenAI is constructed once and reused across entries so the
    # underlying httpx connection pool is shared. Keep timeout per-call
    # (set in the generator), not at client level.
    from openai import AsyncOpenAI

    openai_client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        timeout=15.0,
    )
    s3_client = S3Client(bucket=settings.drive_s3_bucket)

    generator = AliasGenerator(
        openai_client=openai_client,
        s3_client=s3_client,
        model=args.model,
    )

    # Selection happens in a fresh session — we hold the read until
    # the loop runs; per-row writes use a separate session each so a
    # single bad row can't poison the whole batch.
    async with factory() as session:
        repo = ProductCatalogRepository(session)
        entries = await repo.find_entries_needing_aliases(
            current_prompt_version=generator.prompt_version,
            org_id=org_id,
            video_id=video_uuid,
            limit=args.limit,
        )

    logger.info(
        "alias_backfill_selection",
        extra={
            "selected_count": len(entries),
            "org": args.org,
            "video": args.video,
            "current_prompt_version": generator.prompt_version,
            "dry_run": args.dry_run,
        },
    )

    if not entries:
        print("No entries need alias generation. Exiting.")
        return 0

    if args.dry_run:
        print(f"[dry-run] {len(entries)} entries would be processed:")
        for e in entries[:20]:
            print(f"  {e.id}  org={e.org_id}  label={e.llm_label!r}")
        if len(entries) > 20:
            print(f"  ... ({len(entries) - 20} more)")
        return 0

    stats = {"ok": 0, "terminal": 0, "retryable": 0, "skipped_budget": 0}
    total_cost_usd = 0.0
    total_aliases = 0
    start = time.monotonic()
    exit_code = 0

    for i, entry in enumerate(entries, start=1):
        if total_cost_usd >= args.max_cost_usd:
            logger.warning(
                "alias_backfill_max_cost_reached",
                extra={
                    "spent_usd": total_cost_usd,
                    "max_cost_usd": args.max_cost_usd,
                    "remaining": len(entries) - i + 1,
                },
            )
            stats["skipped_budget"] = len(entries) - i + 1
            exit_code = 2
            break

        try:
            result = await generator.generate(
                canonical_crop_s3_key=entry.canonical_crop_s3_key,
                llm_label=entry.llm_label,
            )
        except AliasGenerationBudgetExceeded as e:
            logger.warning("alias_backfill_budget_exceeded", extra={"error": str(e)})
            exit_code = 2
            break
        except AliasGenerationTerminal as e:
            stats["terminal"] += 1
            logger.warning(
                "alias_backfill_entry_terminal",
                extra={
                    "entry_id": str(entry.id),
                    "label": entry.llm_label[:80],
                    "error": str(e)[:300],
                },
            )
            continue
        except AliasGenerationRetryable as e:
            stats["retryable"] += 1
            logger.warning(
                "alias_backfill_entry_retryable",
                extra={
                    "entry_id": str(entry.id),
                    "label": entry.llm_label[:80],
                    "error": str(e)[:300],
                },
            )
            continue
        except AliasGenerationError as e:
            stats["retryable"] += 1
            logger.warning(
                "alias_backfill_entry_unknown",
                extra={
                    "entry_id": str(entry.id),
                    "label": entry.llm_label[:80],
                    "error": str(e)[:300],
                },
            )
            continue

        # Per-entry session so a write failure on one row does not
        # roll back the previous successful writes.
        async with factory() as session:
            repo = ProductCatalogRepository(session)
            updated = await repo.update_aliases(
                entry_id=entry.id,
                aliases=result.aliases,
                prompt_version=result.prompt_version,
            )
            await session.commit()
            if not updated:
                logger.warning(
                    "alias_backfill_row_vanished",
                    extra={"entry_id": str(entry.id)},
                )

        stats["ok"] += 1
        total_cost_usd += result.cost_usd
        total_aliases += len(result.aliases)
        print(
            f"  [{i}/{len(entries)}] {entry.llm_label[:40]:40s} → "
            f"{len(result.aliases):2d} aliases  "
            f"({result.latency_ms} ms, ${result.cost_usd:.5f}): "
            f"{result.aliases}"
        )

    elapsed = time.monotonic() - start
    print(
        f"\nDone in {elapsed:.1f}s — "
        f"ok={stats['ok']}, terminal_fail={stats['terminal']}, "
        f"retryable_fail={stats['retryable']}, "
        f"skipped_budget={stats['skipped_budget']}, "
        f"avg_aliases={total_aliases / stats['ok']:.1f} per entry, "
        f"total_cost_usd=${total_cost_usd:.4f}"
        if stats["ok"]
        else f"\nDone in {elapsed:.1f}s — no entries processed; "
        f"terminal_fail={stats['terminal']}, "
        f"retryable_fail={stats['retryable']}, "
        f"skipped_budget={stats['skipped_budget']}"
    )

    return exit_code if exit_code else (1 if stats["terminal"] + stats["retryable"] else 0)


def main() -> None:
    args = _build_parser().parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
