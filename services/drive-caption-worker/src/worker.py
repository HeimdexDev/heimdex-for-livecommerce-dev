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
        if _global_active >= settings.drive_caption_concurrency:
            return False
        _global_active += 1
        return True


def _release_slot() -> None:
    global _global_active
    with _global_lock:
        _global_active = max(0, _global_active - 1)


async def poll_and_process(api_client, caption_engine=None) -> None:
    get_settings = importlib.import_module("heimdex_worker_sdk.settings").get_worker_settings
    process_caption_pending_files = importlib.import_module("src.tasks.caption").process_caption_pending_files

    settings = get_settings()

    if not settings.scene_caption_enabled:
        return

    if not _acquire_slot(settings):
        return

    try:
        await process_caption_pending_files(
            api_client=api_client, settings=settings, caption_engine=caption_engine,
        )
    except Exception:
        logger.exception("caption_poll_cycle_failed")
    finally:
        _release_slot()


def main() -> None:
    get_settings = importlib.import_module("heimdex_worker_sdk.settings").get_worker_settings
    AsyncIOScheduler = importlib.import_module("apscheduler.schedulers.asyncio").AsyncIOScheduler
    InternalAPIClient = importlib.import_module("heimdex_worker_sdk.internal_api").InternalAPIClient

    settings = get_settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if not settings.scene_caption_enabled:
        logger.info("drive_caption_disabled")
        signal.pause()
        return

    api_client = InternalAPIClient(
        base_url=settings.drive_api_base_url,
        api_key=settings.drive_internal_api_key,
    )

    create_caption_engine = importlib.import_module("heimdex_media_pipelines.vision").create_caption_engine
    engine_key = getattr(settings, "caption_engine", "internvl2")
    if engine_key == "llama_http":
        caption_engine = create_caption_engine(
            model="llama_http",
            base_url=getattr(settings, "llama_caption_url", "http://llama-caption-server:8089"),
            api_key=getattr(settings, "llama_caption_api_key", ""),
        )
    else:
        model_key = "internvl2"
        if "florence" in settings.drive_caption_model.lower():
            model_key = "florence2"
        caption_engine = create_caption_engine(model=model_key, use_gpu=False)
    logger.info("caption_engine_loaded_once", extra={"model": settings.drive_caption_model})

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        poll_and_process,
        "interval",
        seconds=settings.drive_caption_poll_interval_seconds,
        args=[api_client, caption_engine],
        max_instances=1,
        id="caption_poll",
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
            "caption_worker_started",
            extra={
                "poll_interval": settings.drive_caption_poll_interval_seconds,
                "concurrency": settings.drive_caption_concurrency,
            },
        )
        await stop_event.wait()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
