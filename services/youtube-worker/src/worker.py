import asyncio
import logging
import signal
import importlib
from pathlib import Path

from src.config import get_settings
from src.tasks.cleanup import cleanup_completed_videos
from src.tasks.download import process_pending_downloads
from src.tasks.enumerate import sync_all_channels

logger = logging.getLogger(__name__)
AsyncIOScheduler = importlib.import_module("apscheduler.schedulers.asyncio").AsyncIOScheduler
YouTubeAPIClient = importlib.import_module("heimdex_worker_sdk.youtube_api").YouTubeAPIClient


async def run_sync_cycle(api_client) -> None:
    settings = get_settings()
    if not settings.youtube_enabled:
        return

    try:
        created_count = sync_all_channels(api_client, settings)
        downloaded_count = process_pending_downloads(api_client, settings)
        logger.info(
            "youtube_sync_cycle_complete",
            extra={
                "created_count": created_count,
                "downloaded_count": downloaded_count,
            },
        )
    except Exception:
        logger.exception("youtube_sync_cycle_failed")


async def run_cleanup_cycle(api_client) -> None:
    settings = get_settings()
    if not settings.youtube_enabled or not settings.youtube_auto_delete_originals:
        return
    try:
        deleted_count = cleanup_completed_videos(api_client, settings)
        logger.info("youtube_cleanup_cycle_complete", extra={"deleted_count": deleted_count})
    except Exception:
        logger.exception("youtube_cleanup_cycle_failed")


def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if not settings.youtube_enabled:
        logger.info("youtube_worker_disabled, worker sleeping indefinitely")
        signal.pause()
        return

    api_client = YouTubeAPIClient(
        base_url=settings.drive_api_base_url,
        api_key=settings.drive_internal_api_key,
        org_id=settings.youtube_org_id,
    )

    Path(settings.youtube_temp_dir).mkdir(parents=True, exist_ok=True)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_sync_cycle,
        "interval",
        seconds=settings.youtube_sync_interval_seconds,
        args=[api_client],
        max_instances=1,
        id="youtube_sync_poll",
    )
    scheduler.add_job(
        run_cleanup_cycle,
        "interval",
        hours=1,
        args=[api_client],
        max_instances=1,
        id="youtube_cleanup_poll",
    )

    async def _run() -> None:
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()

        def shutdown(*_: object) -> None:
            logger.info("shutdown_signal_received")
            scheduler.shutdown(wait=False)
            stop_event.set()

        loop.add_signal_handler(signal.SIGTERM, shutdown)
        loop.add_signal_handler(signal.SIGINT, shutdown)

        scheduler.start()
        logger.info(
            "youtube_worker_started",
            extra={
                "sync_interval_seconds": settings.youtube_sync_interval_seconds,
                "cleanup_hourly": True,
                "max_concurrent_downloads": settings.youtube_max_concurrent_downloads,
                "temp_dir": settings.youtube_temp_dir,
            },
        )
        await stop_event.wait()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
