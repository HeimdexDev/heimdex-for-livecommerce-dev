import asyncio
import importlib
import logging
import signal
import sys
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Shared concurrency semaphore — acquired by SQS consumer for backpressure control.
_semaphore: Optional[threading.Semaphore] = None


def _init_semaphore(max_concurrent: int) -> threading.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = threading.Semaphore(max_concurrent)
    return _semaphore


def _make_sqs_callback(api_client, settings, ocr_engine):
    """Create the SQS message callback for OCR processing."""
    from heimdex_worker_sdk.message_adapters import sqs_to_claimed_file
    _process_single_ocr = importlib.import_module("src.tasks.ocr")._process_single_ocr

    def callback(message):
        claimed_file = sqs_to_claimed_file(message)
        _process_single_ocr(
            api_client=api_client,
            settings=settings,
            claimed_file=claimed_file,
            ocr_engine=ocr_engine,
        )

    return callback


def main() -> None:
    get_settings = importlib.import_module("heimdex_worker_sdk.settings").get_worker_settings
    InternalAPIClient = importlib.import_module("heimdex_worker_sdk.internal_api").InternalAPIClient

    settings = get_settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if not settings.drive_ocr_enabled:
        logger.info("drive_ocr_disabled")
        signal.pause()
        return

    api_client = InternalAPIClient(
        base_url=settings.drive_api_base_url,
        api_key=settings.drive_internal_api_key,
    )

    create_ocr_engine = importlib.import_module("heimdex_media_pipelines.ocr").create_ocr_engine
    ocr_engine = create_ocr_engine(lang="korean", use_gpu=settings.use_gpu)
    logger.info("ocr_engine_loaded_once")

    # Initialize shared semaphore before starting any consumers
    semaphore = _init_semaphore(settings.drive_ocr_concurrency)

    # ── SQS Consumer (primary job source) ──────────────────────────────────────
    if settings.queue_backend == "rabbitmq":
        pass
    elif not settings.sqs_consumer_enabled or not settings.sqs_ocr_queue_url:
        logger.error("sqs_consumer_required_but_not_configured", extra={"queue": "ocr"})
        sys.exit(1)

    from heimdex_worker_sdk import build_queue_client, ConsumerLoop

    queue_client = build_queue_client("ocr", settings)
    sqs_consumer = ConsumerLoop(
        sqs_client=queue_client,
        process_callback=_make_sqs_callback(api_client, settings, ocr_engine),
        semaphore=semaphore,
        visibility_timeout=60,
        heartbeat_interval=40,
        worker_name="ocr",
    )
    sqs_consumer.start()

    async def _run() -> None:
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()

        def shutdown(*_: object) -> None:
            logger.info("shutdown_signal_received")
            sqs_consumer.stop(timeout=30.0)
            stop_event.set()

        loop.add_signal_handler(signal.SIGTERM, shutdown)
        loop.add_signal_handler(signal.SIGINT, shutdown)

        logger.info(
            "ocr_worker_started",
            extra={
                "concurrency": settings.drive_ocr_concurrency,
                "max_frames_per_video": settings.drive_ocr_max_frames_per_video,
                "sqs_consumer_enabled": settings.sqs_consumer_enabled,
            },
        )
        await stop_event.wait()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
