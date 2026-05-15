"""Nightly cleanup: delete expired shorts-render jobs from S3 + DB.

Usage:
    python -m app.cli.cleanup_shorts_renders              # real cleanup
    python -m app.cli.cleanup_shorts_renders --dry-run    # print-only, no side effects

Exit codes:
    0  success (including empty runs and runs with partial failures)
    1  fatal error before the sweep started (bad config, DB unreachable)

Called from the nightly GitHub Actions workflow in
.github/workflows/cleanup-shorts-renders.yml, which SSHes to EC2 and runs
the command via ``docker compose exec -T api``.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Delete expired shorts-render jobs from S3 and the DB.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be deleted without touching S3 or the DB.",
    )
    return parser.parse_args()


async def _run(dry_run: bool) -> int:
    # Lazy imports: keep module import cheap so `--help` never touches the DB.
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.config import get_settings
    from app.db.base import get_async_engine
    import app.db.models  # noqa: F401 — register model registry
    from app.modules.shorts_render.repository import ShortsRenderJobRepository
    from app.modules.shorts_render.service import cleanup_expired_renders
    from app.storage.s3 import S3Client

    settings = get_settings()
    bucket = settings.drive_s3_bucket
    if not bucket:
        logger.error("drive_s3_bucket is not configured; refusing to run.")
        return 1

    s3_client = S3Client(bucket=bucket)
    engine = get_async_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        repo = ShortsRenderJobRepository(session)
        result = await cleanup_expired_renders(
            repo,
            s3_client,
            dry_run=dry_run,
        )
        if not dry_run:
            await session.commit()

    logger.info(
        "cleanup done: total_expired=%d s3_deleted=%d s3_skipped_not_found=%d "
        "s3_failed=%d db_deleted=%d dry_run=%s",
        result.total_expired,
        result.s3_deleted,
        result.s3_skipped_not_found,
        result.s3_failed,
        result.db_deleted,
        result.dry_run,
    )
    if result.s3_failed:
        logger.warning(
            "%d S3 deletes failed; those rows stay in DB for retry next run.",
            result.s3_failed,
        )
    return 0


def main() -> None:
    args = _parse_args()
    try:
        exit_code = asyncio.run(_run(dry_run=args.dry_run))
    except Exception:
        logger.exception("cleanup_shorts_renders crashed")
        sys.exit(1)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
