"""drive-blur-worker — SQS consumer for user-triggered PII blur jobs.

Mirrors drive-face-worker/src/worker.py in shape so devops operates a
single pattern across GPU workers. The only substantive difference is
that the heavy model (BlurPipeline = OWLv2 + SCRFD) is warmed up once at
boot instead of on first message.

Boot sequence:
  1. Load WorkerSettings (pydantic-settings → env)
  2. Refuse to start if blur_enabled=false OR (no GPU AND blur_allow_cpu=false)
  3. Warm up BlurPipeline (loads OWLv2 + SCRFD into GPU memory)
  4. Build the SQS consumer loop bound to sqs_blur_queue_url
  5. Block on SIGTERM / SIGINT
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import signal
import sys
import threading
from typing import Optional

from heimdex_worker_sdk import emit_event

logger = logging.getLogger(__name__)
_SERVICE_NAME = "drive-blur-worker"

# Shared concurrency semaphore — 1 by default. OWLv2 on the base model
# saturates an L4/A10-class GPU on a single video; parallelizing inside
# one process just causes OOMs without meaningful throughput gains.
_semaphore: Optional[threading.Semaphore] = None


def _init_semaphore(max_concurrent: int) -> threading.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = threading.Semaphore(max_concurrent)
    return _semaphore


def _gpu_available() -> bool:
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _build_blur_pipeline(settings):
    """Construct and warm up the BlurPipeline singleton.

    Imported lazily so the settings check can reject CPU-mode runs
    without blur_allow_cpu=true before we ever touch torch.
    """
    from heimdex_media_pipelines.blur import BlurConfig, BlurPipeline

    config = BlurConfig(
        owl_model=settings.blur_owl_model,
        owl_stride=settings.blur_owl_stride,
        owl_score_threshold=settings.blur_owl_score_threshold,
        use_gpu=settings.use_gpu,
    )
    pipeline = BlurPipeline(config)
    pipeline.warm_up()
    return pipeline


def _make_sqs_callback(api_base_url, internal_api_key, settings, pipeline):
    """Bind the per-message dispatcher to its long-lived dependencies.

    The dispatcher routes by message ``type`` field to either the
    blur-job handler or the layer-export handler. One queue, two
    message types — keeps the worker footprint unchanged while
    unlocking v0.10 layer exports.
    """
    dispatch = importlib.import_module("src.dispatcher").dispatch

    def callback(message) -> None:
        dispatch(
            message,
            api_base_url=api_base_url,
            internal_api_key=internal_api_key,
            settings=settings,
            pipeline=pipeline,
        )

    return callback


def main() -> None:
    get_settings = importlib.import_module(
        "heimdex_worker_sdk.settings"
    ).get_worker_settings
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
    log = structlog.get_logger(__name__)

    # --- fail fast on a broken configuration ---
    if not getattr(settings, "blur_enabled", False):
        log.error("blur_worker_refusing_to_start",
                  reason="BLUR_ENABLED is false")
        sys.exit(1)
    if not settings.sqs_consumer_enabled or not settings.sqs_blur_queue_url:
        log.error("sqs_consumer_required_but_not_configured", queue="blur")
        sys.exit(1)

    gpu_available = _gpu_available()
    if not gpu_available and not getattr(settings, "blur_allow_cpu", False):
        log.error(
            "blur_worker_refusing_cpu_mode",
            reason="OWLv2 on CPU is not operationally viable; "
                   "set BLUR_ALLOW_CPU=true for dev/test only",
        )
        sys.exit(1)

    log.info("blur_worker_booting",
             gpu=gpu_available,
             concurrency=getattr(settings, "drive_blur_concurrency", 1),
             owl_model=settings.blur_owl_model)

    pipeline = _build_blur_pipeline(settings)
    log.info("blur_worker_pipeline_ready")

    semaphore = _init_semaphore(getattr(settings, "drive_blur_concurrency", 1))

    build_queue_client = importlib.import_module("heimdex_worker_sdk").build_queue_client
    ConsumerLoop = importlib.import_module("heimdex_worker_sdk").ConsumerLoop

    queue_client = build_queue_client("blur", settings)
    sqs_consumer = ConsumerLoop(
        sqs_client=queue_client,
        process_callback=_make_sqs_callback(
            settings.drive_api_base_url,
            settings.drive_internal_api_key,
            settings,
            pipeline,
        ),
        semaphore=semaphore,
        visibility_timeout=settings.blur_lease_seconds if hasattr(settings, "blur_lease_seconds") else 1800,
        heartbeat_interval=300,
        worker_name="blur",
    )
    sqs_consumer.start()

    async def _run() -> None:
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()

        def shutdown(*_: object) -> None:
            log.info("shutdown_signal_received")
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
        log.info("blur_worker_started")
        emit_event(
            service=_SERVICE_NAME,
            event_name="worker_started",
            category="worker_lifecycle",
            level="INFO",
            metadata={
                "concurrency": getattr(settings, "drive_blur_concurrency", 1),
                "owl_model": settings.blur_owl_model,
                "gpu": gpu_available,
            },
        )
        await stop_event.wait()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
