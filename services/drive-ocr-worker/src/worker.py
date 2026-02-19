import asyncio
import importlib
import logging
import signal
from threading import Lock

logger = logging.getLogger(__name__)

_global_active = 0
_global_lock = Lock()


def _acquire_slot(settings) -> bool:
    global _global_active
    with _global_lock:
        if _global_active >= settings.drive_ocr_concurrency:
            return False
        _global_active += 1
        return True


def _release_slot() -> None:
    global _global_active
    with _global_lock:
        _global_active = max(0, _global_active - 1)


async def poll_and_process(session_factory) -> None:
    get_settings = importlib.import_module("app.config").get_settings
    process_ocr_pending_files = importlib.import_module("src.tasks.ocr").process_ocr_pending_files

    settings = get_settings()

    if not settings.drive_ocr_enabled:
        return

    if not _acquire_slot(settings):
        return

    async with session_factory() as session:
        try:
            await process_ocr_pending_files(session=session, settings=settings)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("ocr_poll_cycle_failed")
        finally:
            _release_slot()


def main() -> None:
    get_settings = importlib.import_module("app.config").get_settings
    AsyncIOScheduler = importlib.import_module("apscheduler.schedulers.asyncio").AsyncIOScheduler
    sqlalchemy_asyncio = importlib.import_module("sqlalchemy.ext.asyncio")
    create_async_engine = sqlalchemy_asyncio.create_async_engine
    async_sessionmaker = sqlalchemy_asyncio.async_sessionmaker
    AsyncSession = sqlalchemy_asyncio.AsyncSession

    settings = get_settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if not settings.drive_ocr_enabled:
        logger.info("drive_ocr_disabled")
        signal.pause()
        return

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        poll_and_process,
        "interval",
        seconds=settings.drive_ocr_poll_interval_seconds,
        args=[session_factory],
        max_instances=1,
        id="ocr_poll",
    )

    loop = asyncio.new_event_loop()

    def shutdown(*_):
        logger.info("shutdown_signal_received")
        scheduler.shutdown(wait=False)
        loop.stop()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    scheduler.start()
    logger.info(
        "ocr_worker_started",
        extra={
            "poll_interval": settings.drive_ocr_poll_interval_seconds,
            "concurrency": settings.drive_ocr_concurrency,
            "max_frames_per_video": settings.drive_ocr_max_frames_per_video,
        },
    )

    try:
        loop.run_forever()
    finally:
        loop.close()


if __name__ == "__main__":
    main()
