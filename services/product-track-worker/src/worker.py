"""product-track-worker — SQS consumer for shorts-auto product mode v2
tracking jobs.

Mirrors product-enumerate-worker/src/worker.py in shape. The
substantive change vs enumerate: SAM2 replaces the gpt-4o-mini
batch loop as the warm-up cost — SigLIP2 is reused (already loaded
by drive-visual-embed-worker; same singleton shared across the
pipeline lib).

Boot sequence:
  1. Load WorkerSettings (pydantic-settings → env)
  2. Refuse to start if product_v2_enabled=false OR (no GPU AND
     track_allow_cpu=false)
  3. Warm up SigLIP2 (loads google/siglip2-base-patch16-256)
  4. Warm up SAM2 (loads facebook/sam2-hiera-base-plus, see
     sam2_loader.py)
  5. Build the SQS consumer loop bound to sqs_product_track_queue_url
  6. Block on SIGTERM / SIGINT
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import signal
import sys
import threading

from heimdex_worker_sdk import emit_event

from src.settings import WorkerSettings

logger = logging.getLogger(__name__)
_SERVICE_NAME = "product-track-worker"


_semaphore: threading.Semaphore | None = None


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


def _warm_siglip2(settings: WorkerSettings) -> None:
    """Load + warm SigLIP2 once at boot — same pattern as the
    enumerate-worker. Idempotent on subsequent calls."""
    from heimdex_media_pipelines.siglip2 import SiglipConfig, load
    load(SiglipConfig(model_id=settings.siglip2_model_id))


def _warm_sam2(settings: WorkerSettings) -> None:
    """Load + warm SAM2 once at boot. See ``sam2_loader.py`` for the
    actual implementation; this is just the singleton primer."""
    from src.sam2_loader import load_sam2
    load_sam2(model_id=settings.sam2_model_id)


def _make_callback(settings: WorkerSettings):
    """Bind the per-message dispatcher to its long-lived deps."""
    dispatch = importlib.import_module("src.dispatcher").dispatch

    def callback(message) -> None:
        dispatch(message, settings=settings)

    return callback


def main() -> None:
    settings = WorkerSettings()

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

    # --- fail fast on safety flags ---
    if not settings.product_v2_enabled:
        log.error(
            "track_worker_refusing_to_start",
            reason="AUTO_SHORTS_PRODUCT_V2_ENABLED is false",
        )
        sys.exit(1)

    if not _gpu_available() and not settings.track_allow_cpu:
        log.error(
            "track_worker_refusing_to_start",
            reason="No GPU available and TRACK_ALLOW_CPU=false",
        )
        sys.exit(1)

    if not settings.sqs_consumer_enabled or not settings.sqs_product_track_queue_url:
        log.error(
            "track_worker_refusing_to_start",
            reason=(
                "SQS_CONSUMER_ENABLED=false or SQS_PRODUCT_TRACK_QUEUE_URL is empty"
            ),
            sqs_consumer_enabled=settings.sqs_consumer_enabled,
            queue_url_set=bool(settings.sqs_product_track_queue_url),
        )
        sys.exit(1)

    if not settings.drive_internal_api_key:
        log.error(
            "track_worker_refusing_to_start",
            reason="DRIVE_INTERNAL_API_KEY is empty",
        )
        sys.exit(1)

    # --- warm models ---
    log.info("track_worker_warming_models")
    try:
        _warm_siglip2(settings)
    except Exception:
        log.exception("siglip2_warm_failed")
        sys.exit(1)

    # SAM2 is real as of Phase 3c-B. Any failure during warmup
    # (missing weights, CUDA OOM, transformers API drift, model
    # download timeout) is a hard boot failure — operators see
    # ``sam2_warm_failed`` immediately rather than discovering it
    # per-job. The Phase 3c-A NotImplementedError tolerance is
    # gone now that the loader actually loads.
    try:
        _warm_sam2(settings)
    except Exception:
        log.exception("sam2_warm_failed")
        sys.exit(1)
    log.info("track_worker_models_warmed")

    semaphore = _init_semaphore(settings.drive_product_track_concurrency)

    # --- build the SQS consumer ---
    # F1 fix: ConsumerLoop's signature requires sqs_client /
    # process_callback / semaphore (no defaults — the missing
    # ``semaphore`` arg made every prior boot fail with TypeError).
    # Worker-name "product_track" matches the existing
    # gpu_orchestrator._JOB_TYPE_TO_WORKER convention; the heartbeat
    # interval mirrors product-enumerate-worker.
    from heimdex_worker_sdk import build_queue_client
    from heimdex_worker_sdk.sqs_consumer import ConsumerLoop

    queue_client = build_queue_client(
        queue_name="product_track",
        settings=settings,  # type: ignore[arg-type]
    )
    consumer = ConsumerLoop(
        sqs_client=queue_client,
        process_callback=_make_callback(settings),
        semaphore=semaphore,
        visibility_timeout=settings.worker_lease_seconds,
        heartbeat_interval=300,
        worker_name="product_track",
    )

    emit_event(
        service=_SERVICE_NAME,
        event_name="worker_started",
        category="worker_lifecycle",
        level="INFO",
        metadata={"worker_id": settings.worker_id},
    )

    # --- shutdown handlers ---
    stop_event = threading.Event()

    def _shutdown(*_: object) -> None:
        log.info("shutdown_signal_received")
        emit_event(
            service=_SERVICE_NAME,
            event_name="worker_stopping",
            category="worker_lifecycle",
            level="INFO",
            metadata={"worker_id": settings.worker_id},
        )
        consumer.stop(timeout=30.0)
        stop_event.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    log.info(
        "track_worker_started",
        worker_id=settings.worker_id,
        concurrency=settings.drive_product_track_concurrency,
        lease_seconds=settings.worker_lease_seconds,
    )

    consumer.start()
    stop_event.wait()


if __name__ == "__main__":
    main()
