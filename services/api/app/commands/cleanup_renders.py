"""Management command: clean up expired render outputs from S3 and DB.

Usage:
    docker compose exec api python -m app.commands.cleanup_renders
"""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.logging_config import get_logger, setup_logging
from app.modules.shorts_render.repository import ShortsRenderJobRepository

setup_logging()
logger = get_logger(__name__)


async def cleanup_expired_renders(
    session: AsyncSession,
    s3_client,
    bucket: str,
) -> int:
    """Delete expired render outputs from S3 and clear DB fields.

    Returns count of cleaned jobs.
    """
    repo = ShortsRenderJobRepository(session)
    now = datetime.now(timezone.utc)

    expired_jobs = await repo.list_expired(now)
    if not expired_jobs:
        logger.info(
            "render_cleanup_completed",
            total=0,
            cleaned=0,
        )
        return 0

    cleaned = 0
    for job in expired_jobs:
        try:
            s3_client.delete(job.output_s3_key)
            logger.info(
                "render_output_deleted",
                job_id=str(job.id),
                s3_key=job.output_s3_key,
            )
        except Exception:
            logger.exception(
                "render_output_delete_failed",
                job_id=str(job.id),
                s3_key=job.output_s3_key,
            )
            continue

        job.output_s3_key = None
        job.output_size_bytes = None
        cleaned += 1

    await session.flush()

    logger.info(
        "render_cleanup_completed",
        total=len(expired_jobs),
        cleaned=cleaned,
    )
    return cleaned


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    from app.storage.s3 import S3Client

    s3 = S3Client(bucket=settings.drive_s3_bucket)

    async with session_factory() as session:
        cleaned = await cleanup_expired_renders(session, s3, settings.drive_s3_bucket)
        await session.commit()

    logger.info("cleanup_command_finished", cleaned=cleaned)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
