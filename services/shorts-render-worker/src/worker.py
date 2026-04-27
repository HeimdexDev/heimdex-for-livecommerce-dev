import asyncio
import importlib
import logging
import signal
import sys
import threading

from heimdex_worker_sdk import emit_event

logger = logging.getLogger(__name__)
_SERVICE_NAME = "shorts-render-worker"
_semaphore: threading.Semaphore | None = None


def _init_semaphore(max_concurrent: int) -> threading.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = threading.Semaphore(max_concurrent)
    return _semaphore


def _make_sqs_callback(api_client, settings):
    from src.message_adapter import sqs_to_render_job

    _process_render = importlib.import_module("src.tasks.render").process_render_job

    def callback(message):
        render_job = sqs_to_render_job(message)
        _process_render(
            api_client=api_client,
            settings=settings,
            render_job=render_job,
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

    api_client = InternalAPIClient(
        base_url=settings.drive_api_base_url,
        api_key=settings.drive_internal_api_key,
    )

    semaphore = _init_semaphore(2)

    if settings.queue_backend == "rabbitmq":
        pass
    elif not settings.sqs_consumer_enabled or not settings.sqs_shorts_render_queue_url:
        logger.error("sqs_consumer_required_but_not_configured", extra={"queue": "shorts_render"})
        sys.exit(1)

    from heimdex_worker_sdk import build_queue_client, ConsumerLoop

    queue_client = build_queue_client("shorts_render", settings)
    sqs_consumer = ConsumerLoop(
        sqs_client=queue_client,
        process_callback=_make_sqs_callback(api_client, settings),
        semaphore=semaphore,
        visibility_timeout=1800,
        heartbeat_interval=300,
        worker_name="shorts-render",
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
            "shorts_render_worker_started",
            extra={
                "sqs_consumer_enabled": settings.sqs_consumer_enabled,
            },
        )
        emit_event(
            service=_SERVICE_NAME,
            event_name="worker_started",
            category="worker_lifecycle",
            level="INFO",
            metadata={
                "sqs_consumer_enabled": settings.sqs_consumer_enabled,
            },
        )
        _ = await stop_event.wait()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
