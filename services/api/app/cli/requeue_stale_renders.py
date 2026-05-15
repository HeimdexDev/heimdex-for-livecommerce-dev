"""Requeue shorts_render_jobs rows stuck in 'queued' beyond a threshold.

Why this exists
===============

The shorts-render-worker uses ``heimdex-worker-sdk``'s SQS consumer
loop. Even with the 0.4.0 watchdog (heartbeat + 1h proactive client
refresh + hung-poll detection), boto3's long-poll connection can
silently drop messages — ``receive_jobs`` returns empty quickly even
though SQS has visible messages waiting. The watchdog only catches
HUNG ``receive_jobs`` calls, not fast-empty-with-pending-work. Until
the SDK ships a queue-depth-aware watchdog (Fix A in
``.claude/plans/sqs-wedge-investigation-2026-05-07.md``), ``queued``
rows can sit in the database indefinitely while the worker idly
polls an empty stream.

This janitor is the safety net. It scans for ``shorts_render_jobs``
rows that have been ``status='queued'`` longer than the threshold
(default 5 minutes) and republishes each one to SQS. The worker —
even if previously wedged — picks them up on its next healthy poll.

The fix is intentionally additive: nothing about the rest of the
pipeline changes. Worker-callback idempotency (``complete_idempotent``
in ``shorts_render/repository.py``) collapses double-completes
silently, so a stale row that the worker is *actually* about to
process gets republished, then the worker processes one of the two
copies and the other is auto-deleted as a no-op.

Usage
=====

::

    python -m app.cli.requeue_stale_renders                     # default 5-min threshold
    python -m app.cli.requeue_stale_renders --dry-run           # report only
    python -m app.cli.requeue_stale_renders --stale-minutes 15  # tune threshold
    python -m app.cli.requeue_stale_renders --limit 100         # cap batch size

Behaviour
=========

- Selects ``ShortsRenderJob`` rows where ``status='queued'`` AND
  ``created_at < NOW() - INTERVAL ':stale_minutes minutes'``.
- For each: re-publishes via the same ``publish_shorts_render_job``
  helper the API uses on first publish, so the message shape +
  side-effect chain is identical to the happy path.
- Does NOT mutate the row. ``status='queued'`` is correct — the
  re-publish is idempotent at the worker callback (the worker's
  ``complete_idempotent`` handler returns early if status is already
  past 'queued' by the time the second copy lands).
- Per-row publish failures are logged + skipped, never abort the
  sweep.

Cron
====

Wired by ``.github/workflows/requeue-stale-renders.yml`` —
runs every 5 minutes on staging + production. On-demand:

::

    ssh ec2-user@<host> "cd /opt/heimdex/dev-heimdex-for-livecommerce && \\
        docker compose exec -T api python -m app.cli.requeue_stale_renders --dry-run"

Exit codes
==========

- ``0`` success (zero or more rows processed, including partial failures)
- ``1`` fatal pre-sweep error (config invalid, DB unreachable, SQS not configured)

Limitations
===========

- Threshold is wall-clock based on ``created_at``. A render that
  legitimately takes >5min to start (e.g. visibility-timeout heartbeat
  while a long FFmpeg job runs ahead of it) will be republished.
  Idempotency at the worker absorbs the redundant message; no
  double-render happens.
- The SDK's ``publish_shorts_render_job`` raises on send failure;
  the per-row try/except below treats that as a soft skip rather
  than aborting. We log + continue so one bad row doesn't prevent
  the rest of the sweep.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


# Default threshold balances "fast recovery" against "don't pile
# duplicates onto a worker that's just slow". 5 min matches the
# cron interval — at most one duplicate per stuck row per cycle.
_DEFAULT_STALE_MINUTES = 5


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Republish shorts_render_jobs rows stuck in 'queued' beyond "
            "the staleness threshold."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print rows that would be requeued; do not publish.",
    )
    parser.add_argument(
        "--stale-minutes",
        type=int,
        default=_DEFAULT_STALE_MINUTES,
        help=(
            f"Minimum age (minutes since created_at) for a 'queued' row "
            f"to be considered stale. Default: {_DEFAULT_STALE_MINUTES}."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of rows to requeue this run. Default: no limit.",
    )
    return parser.parse_args()


async def _run(*, dry_run: bool, stale_minutes: int, limit: int | None) -> int:
    # Lazy imports — keep ``--help`` cheap and DB-free.
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.config import get_settings
    from app.db.base import get_async_engine
    import app.db.models  # noqa: F401 — load full ORM registry
    from app.modules.shorts_render.models import ShortsRenderJob
    from app.sqs_producer import publish_shorts_render_job

    if stale_minutes < 1:
        logger.error("--stale-minutes must be >= 1, got %d", stale_minutes)
        return 1

    settings = get_settings()
    if not dry_run:
        if not settings.sqs_enabled:
            logger.error(
                "sqs_enabled is False; refusing to publish "
                "(use --dry-run to inspect candidates)"
            )
            return 1
        if not settings.sqs_shorts_render_queue_url:
            logger.error(
                "sqs_shorts_render_queue_url is not set; refusing to publish"
            )
            return 1

    engine = get_async_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)

    requeued = 0
    failures = 0

    async with factory() as session:
        stmt = (
            select(ShortsRenderJob)
            .where(ShortsRenderJob.status == "queued")
            .where(ShortsRenderJob.created_at < cutoff)
            .order_by(ShortsRenderJob.created_at.asc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)

        result = await session.execute(stmt)
        rows = list(result.scalars().all())

        logger.info(
            "requeue_stale_renders_candidates_found "
            "count=%d dry_run=%s stale_minutes=%d cutoff=%s",
            len(rows),
            dry_run,
            stale_minutes,
            cutoff.isoformat(),
        )

        for row in rows:
            age_seconds = int(
                (datetime.now(timezone.utc) - row.created_at).total_seconds()
            )
            if dry_run:
                logger.info(
                    "requeue_stale_render_would_publish "
                    "job_id=%s org_id=%s video_id=%s age_seconds=%d",
                    str(row.id),
                    str(row.org_id),
                    row.video_id,
                    age_seconds,
                )
                continue

            try:
                publish_shorts_render_job(
                    job_id=row.id,
                    org_id=row.org_id,
                    video_id=row.video_id,
                    input_spec=row.input_spec,
                )
                requeued += 1
                logger.info(
                    "requeue_stale_render "
                    "job_id=%s org_id=%s video_id=%s age_seconds=%d",
                    str(row.id),
                    str(row.org_id),
                    row.video_id,
                    age_seconds,
                )
            except Exception:
                failures += 1
                logger.exception(
                    "requeue_stale_render_publish_failed "
                    "job_id=%s video_id=%s",
                    str(row.id),
                    row.video_id,
                )
                continue

    logger.info(
        "requeue_stale_renders_done dry_run=%s candidates=%d "
        "requeued=%d failures=%d",
        dry_run,
        len(rows),
        requeued,
        failures,
    )
    return 0


def main() -> None:
    args = _parse_args()
    try:
        exit_code = asyncio.run(
            _run(
                dry_run=args.dry_run,
                stale_minutes=args.stale_minutes,
                limit=args.limit,
            )
        )
    except Exception:
        logger.exception("requeue_stale_renders crashed")
        sys.exit(1)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
