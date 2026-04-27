import asyncio
import importlib
import logging
import signal
import sys
import threading
from typing import Optional

from heimdex_worker_sdk import emit_event

logger = logging.getLogger(__name__)
_SERVICE_NAME = "drive-face-worker"

# Shared concurrency semaphore - acquired by SQS consumer for backpressure control.
_semaphore: Optional[threading.Semaphore] = None


def _init_semaphore(max_concurrent: int) -> threading.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = threading.Semaphore(max_concurrent)
    return _semaphore


def _make_sqs_callback(api_client, settings, face_analyzer):
    """Create the SQS message callback for face processing."""
    sqs_to_claimed_file = importlib.import_module(
        "heimdex_worker_sdk.message_adapters"
    ).sqs_to_claimed_file
    _process_single_face_detect = importlib.import_module(
        "src.tasks.face_detect"
    )._process_single_face_detect

    def callback(message):
        claimed_file = sqs_to_claimed_file(message)
        _process_single_face_detect(
            api_client=api_client,
            settings=settings,
            claimed_file=claimed_file,
            face_analyzer=face_analyzer,
        )

    return callback


def main() -> None:
    get_settings = importlib.import_module(
        "heimdex_worker_sdk.settings"
    ).get_worker_settings
    InternalAPIClient = importlib.import_module(
        "heimdex_worker_sdk.internal_api"
    ).InternalAPIClient

    settings = get_settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    structlog = importlib.import_module("structlog")
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    api_client = InternalAPIClient(
        base_url=settings.drive_api_base_url,
        api_key=settings.drive_internal_api_key,
    )

    FaceAnalysis = importlib.import_module("insightface.app").FaceAnalysis
    detect_onnx_providers = importlib.import_module(
        "heimdex_media_pipelines.device"
    ).detect_onnx_providers

    providers = detect_onnx_providers()
    face_analyzer = FaceAnalysis(name="buffalo_l", providers=providers)
    face_analyzer.prepare(
        ctx_id=0 if settings.use_gpu else -1,
        det_size=(640, 640),
        det_thresh=0.5,
    )
    logger = structlog.get_logger(__name__)
    logger.info("face_analyzer_loaded_once", providers=providers, model="buffalo_l")

    semaphore = _init_semaphore(getattr(settings, "drive_face_concurrency", 1))

    if settings.queue_backend == "rabbitmq":
        pass
    elif not settings.sqs_consumer_enabled or not settings.sqs_face_queue_url:
        logger.error("sqs_consumer_required_but_not_configured", queue="face")
        sys.exit(1)

    build_queue_client = importlib.import_module("heimdex_worker_sdk").build_queue_client
    ConsumerLoop = importlib.import_module("heimdex_worker_sdk").ConsumerLoop

    queue_client = build_queue_client("face", settings)
    queue_type = "face"
    sqs_consumer = ConsumerLoop(
        sqs_client=queue_client,
        process_callback=_make_sqs_callback(api_client, settings, face_analyzer),
        semaphore=semaphore,
        visibility_timeout=1800,
        heartbeat_interval=300,
        worker_name=queue_type,
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
            "face_worker_started",
            concurrency=getattr(settings, "drive_face_concurrency", 1),
            sqs_consumer_enabled=settings.sqs_consumer_enabled,
        )
        emit_event(
            service=_SERVICE_NAME,
            event_name="worker_started",
            category="worker_lifecycle",
            level="INFO",
            metadata={
                "concurrency": getattr(settings, "drive_face_concurrency", 1),
                "model": "buffalo_l",
                "providers": providers,
                "sqs_consumer_enabled": settings.sqs_consumer_enabled,
            },
        )
        await stop_event.wait()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
