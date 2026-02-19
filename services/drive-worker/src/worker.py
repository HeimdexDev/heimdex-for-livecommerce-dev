import asyncio
import logging
import shutil
import signal
import sys
from collections import defaultdict
from pathlib import Path
from threading import Lock

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from src.tasks.process import process_pending_files

logger = logging.getLogger(__name__)

_org_slots: dict[str, int] = defaultdict(int)
_org_lock = Lock()
_global_active = 0
_global_lock = Lock()


def _check_disk_budget(temp_dir: Path, budget_gb: float) -> bool:
    if not temp_dir.exists():
        return True
    usage = shutil.disk_usage(temp_dir)
    used_gb = (usage.total - usage.free) / (1024 ** 3)
    return used_gb < budget_gb


def _acquire_slot(org_id: str, settings) -> bool:
    global _global_active
    with _global_lock:
        if _global_active >= settings.drive_worker_global_concurrency:
            return False
        with _org_lock:
            if _org_slots[org_id] >= settings.drive_worker_per_org_concurrency:
                return False
            _global_active += 1
            _org_slots[org_id] += 1
            return True


def _release_slot(org_id: str) -> None:
    global _global_active
    with _global_lock:
        _global_active = max(0, _global_active - 1)
    with _org_lock:
        _org_slots[org_id] = max(0, _org_slots[org_id] - 1)


async def poll_and_process(session_factory: async_sessionmaker[AsyncSession]) -> None:
    settings = get_settings()

    if not settings.drive_connector_enabled:
        return

    temp_dir = Path(settings.drive_temp_dir)
    if not _check_disk_budget(temp_dir, settings.drive_temp_disk_budget_gb):
        logger.warning("disk_budget_exceeded", extra={"temp_dir": str(temp_dir), "budget_gb": settings.drive_temp_disk_budget_gb})
        return

    async with session_factory() as session:
        try:
            await process_pending_files(
                session=session,
                settings=settings,
                acquire_slot=_acquire_slot,
                release_slot=_release_slot,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("poll_cycle_failed")


def main() -> None:
    settings = get_settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if not settings.drive_connector_enabled:
        logger.info("drive_connector_disabled, worker sleeping indefinitely")
        signal.pause()
        return

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    temp_dir = Path(settings.drive_temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        poll_and_process,
        "interval",
        seconds=settings.drive_worker_poll_interval_seconds,
        args=[session_factory],
        max_instances=1,
        id="drive_poll",
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
        "drive_worker_started",
        extra={
            "poll_interval": settings.drive_worker_poll_interval_seconds,
            "global_concurrency": settings.drive_worker_global_concurrency,
            "per_org_concurrency": settings.drive_worker_per_org_concurrency,
            "disk_budget_gb": settings.drive_temp_disk_budget_gb,
        },
    )

    try:
        loop.run_forever()
    finally:
        loop.close()


if __name__ == "__main__":
    main()
