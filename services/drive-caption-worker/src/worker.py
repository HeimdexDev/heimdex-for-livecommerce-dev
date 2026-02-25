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


def _make_sqs_callback(api_client, settings, caption_engine):
    """Create the SQS message callback for caption processing."""
    from heimdex_worker_sdk.message_adapters import sqs_to_claimed_file
    _process_single_caption = importlib.import_module("src.tasks.caption")._process_single_caption

    def callback(message):
        claimed_file = sqs_to_claimed_file(message)
        _process_single_caption(
            api_client=api_client,
            settings=settings,
            claimed_file=claimed_file,
            caption_engine=caption_engine,
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

    # Initialize shared semaphore before starting any consumers
    semaphore = _init_semaphore(settings.drive_caption_concurrency)

    # ── SQS Consumer (primary job source) ──────────────────────────────────────
    if not settings.sqs_consumer_enabled or not settings.sqs_caption_queue_url:
        logger.error("sqs_consumer_required_but_not_configured", extra={"queue": "caption"})
        sys.exit(1)

    from heimdex_worker_sdk.sqs_client import SQSJobClient
    from heimdex_worker_sdk.sqs_consumer import SQSConsumerLoop

    sqs_client = SQSJobClient(
        queue_url=settings.sqs_caption_queue_url,
        region=settings.sqs_region,
        endpoint_url=settings.sqs_endpoint_url or None,
    )
    sqs_consumer = SQSConsumerLoop(
        sqs_client=sqs_client,
        process_callback=_make_sqs_callback(api_client, settings, caption_engine),
        semaphore=semaphore,
        visibility_timeout=60,
        heartbeat_interval=40,
        worker_name="caption",
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
            "caption_worker_started",
            extra={
                "concurrency": settings.drive_caption_concurrency,
                "sqs_consumer_enabled": settings.sqs_consumer_enabled,
            },
        )
        await stop_event.wait()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
