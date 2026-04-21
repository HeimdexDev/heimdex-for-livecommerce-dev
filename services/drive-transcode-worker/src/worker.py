import asyncio
import importlib
import logging
import signal
import sys
import threading

from heimdex_worker_sdk import emit_event

logger = logging.getLogger(__name__)
_SERVICE_NAME = "drive-transcode-worker"
_semaphore: threading.Semaphore | None = None


def _init_semaphore(max_concurrent: int) -> threading.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = threading.Semaphore(max_concurrent)
    return _semaphore


def _make_sqs_callback(api_client, settings):
    from heimdex_worker_sdk.message_adapters import sqs_to_claimed_file

    _process_single_transcode = importlib.import_module("src.tasks.transcode")._process_single_transcode

    def callback(message):
        claimed_file = sqs_to_claimed_file(message)
        _process_single_transcode(
            api_client=api_client,
            settings=settings,
            claimed_file=claimed_file,
            raw_message=message,
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

    if settings.drive_transcode_mode != "gpu":
        logger.info("drive_transcode_disabled", extra={"mode": settings.drive_transcode_mode})
        signal.pause()
        return

    api_client = InternalAPIClient(
        base_url=settings.drive_api_base_url,
        api_key=settings.drive_internal_api_key,
    )

    semaphore = _init_semaphore(settings.drive_worker_global_concurrency)

    if not settings.sqs_consumer_enabled or not settings.sqs_transcode_queue_url:
        logger.error("sqs_consumer_required_but_not_configured", extra={"queue": "transcode"})
        sys.exit(1)

    from heimdex_worker_sdk.sqs_client import SQSJobClient
    from heimdex_worker_sdk.sqs_consumer import SQSConsumerLoop

    sqs_client = SQSJobClient(
        queue_url=settings.sqs_transcode_queue_url,
        region=settings.sqs_region,
        endpoint_url=settings.sqs_endpoint_url or None,
    )
    sqs_consumer = SQSConsumerLoop(
        sqs_client=sqs_client,
        process_callback=_make_sqs_callback(api_client, settings),
        semaphore=semaphore,
        visibility_timeout=1800,
        heartbeat_interval=300,
        worker_name="transcode",
    )
    sqs_consumer.start()

    async def _run() -> None:
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()

        def shutdown(*_: object) -> None:
            logger.info("shutdown_signal_received")
            emit_event(
                service=_SERVICE_NAME,
                event_name="worker_stopping",
                category="worker_lifecycle",
                level="INFO",
            )
            sqs_consumer.stop(timeout=30.0)
            stop_event.set()

        loop.add_signal_handler(signal.SIGTERM, shutdown)
        loop.add_signal_handler(signal.SIGINT, shutdown)

        logger.info(
            "transcode_worker_started",
            extra={
                "concurrency": settings.drive_worker_global_concurrency,
                "mode": settings.drive_transcode_mode,
                "sqs_consumer_enabled": settings.sqs_consumer_enabled,
            },
        )
        emit_event(
            service=_SERVICE_NAME,
            event_name="worker_started",
            category="worker_lifecycle",
            level="INFO",
            metadata={
                "concurrency": settings.drive_worker_global_concurrency,
                "mode": settings.drive_transcode_mode,
                "sqs_consumer_enabled": settings.sqs_consumer_enabled,
            },
        )
        _ = await stop_event.wait()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
