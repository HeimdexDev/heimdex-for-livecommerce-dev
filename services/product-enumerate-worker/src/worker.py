"""product-enumerate-worker — SQS consumer for shorts-auto product
mode v2 enumeration jobs.

Mirrors drive-blur-worker/src/worker.py in shape so devops operates a
single pattern across GPU workers. As of the OWLv2 two-stage refactor
the warmed-up models are **SigLIP2 + OWLv2** (gpt-4o-mini is HTTP-only
and lazily connected — no boot warmup needed).

Boot sequence:
  1. Load WorkerSettings (pydantic-settings → env)
  2. Refuse to start if product_v2_enabled=false OR (no GPU AND
     enumerate_allow_cpu=false)
  3. Warm up SigLIP2 (loads google/siglip2-base-patch16-256)
  4. Warm up OWLv2 (loads google/owlv2-base-patch16-ensemble onto GPU)
  5. Construct OpenAIVlmClient — receives the preloaded OWLv2
     processor/model and the OpenAI API key. No network on boot.
  6. Build the SQS consumer loop bound to sqs_product_enumerate_queue_url
  7. Block on SIGTERM / SIGINT
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import signal
import sys
import threading

from heimdex_worker_sdk import emit_event

from src.openai_vlm import OpenAIVlmClient
from src.settings import WorkerSettings

logger = logging.getLogger(__name__)
_SERVICE_NAME = "product-enumerate-worker"


# Single concurrency by default — gpt-4o-mini calls are I/O-bound but
# SigLIP2 batches saturate one GPU per video. Bumping concurrency
# would only help if the pipeline is split into separately-scheduled
# stages, which is out of Phase 2 scope.
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
    """Load + warm SigLIP2 once at boot — same pattern as the existing
    drive-visual-embed-worker. Idempotent on subsequent calls."""
    from heimdex_media_pipelines.siglip2 import SiglipConfig, load
    load(SiglipConfig(model_id=settings.siglip2_model_id))


def _load_owlv2(settings: WorkerSettings):
    """Load OWLv2 processor + model onto the inference device.

    Returns ``(processor, model, device)``. Run once at boot so per-job
    dispatch doesn't pay the ~600MB weight-load cost on every message.

    Device selection mirrors ``_gpu_available``: CUDA if available,
    otherwise CPU (only reachable when ``enumerate_allow_cpu=true``).
    """
    import torch
    from transformers import Owlv2ForObjectDetection, Owlv2Processor

    device = torch.device(
        "cuda" if torch.cuda.is_available() else "cpu"
    )
    processor = Owlv2Processor.from_pretrained(settings.owlv2_model_id)
    model = Owlv2ForObjectDetection.from_pretrained(
        settings.owlv2_model_id
    ).to(device)
    model.eval()
    return processor, model, device


def _make_callback(settings: WorkerSettings, vlm_client: OpenAIVlmClient):
    """Bind the per-message dispatcher to its long-lived deps."""
    dispatch = importlib.import_module("src.dispatcher").dispatch

    def callback(message) -> None:
        dispatch(message, settings=settings, vlm_client=vlm_client)

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

    # --- fail fast ---
    if not settings.product_v2_enabled:
        log.error(
            "enumerate_worker_refusing_to_start",
            reason="AUTO_SHORTS_PRODUCT_V2_ENABLED is false",
        )
        sys.exit(1)
    if not settings.sqs_consumer_enabled or not settings.sqs_product_enumerate_queue_url:
        log.error("sqs_consumer_required_but_not_configured", queue="product_enumerate")
        sys.exit(1)
    if not settings.openai_api_key:
        log.error("openai_api_key_required")
        sys.exit(1)

    gpu_available = _gpu_available()
    if not gpu_available and not settings.enumerate_allow_cpu:
        log.error(
            "enumerate_worker_refusing_cpu_mode",
            reason="SigLIP2 on CPU is too slow for prod; "
                   "set ENUMERATE_ALLOW_CPU=true for dev/test only",
        )
        sys.exit(1)

    log.info(
        "enumerate_worker_booting",
        gpu=gpu_available,
        siglip2_model=settings.siglip2_model_id,
        owlv2_model=settings.owlv2_model_id,
        openai_model=settings.openai_model,
    )

    _warm_siglip2(settings)
    log.info("siglip2_warmed")

    owlv2_processor, owlv2_model, owlv2_device = _load_owlv2(settings)
    log.info("owlv2_warmed", device=str(owlv2_device))

    vlm_client = OpenAIVlmClient(
        api_key=settings.openai_api_key,
        owlv2_processor=owlv2_processor,
        owlv2_model=owlv2_model,
        owlv2_device=owlv2_device,
        model=settings.openai_model,
        timeout_sec=settings.openai_timeout_sec,
        max_retries=settings.openai_max_retries,
        threshold=settings.owlv2_threshold,
        nms_iou=settings.owlv2_nms_iou,
        max_dets_per_keyframe=settings.owlv2_max_dets_per_keyframe,
        max_image_side=settings.owlv2_max_image_side,
        crop_pad_frac=settings.owlv2_crop_pad_frac,
        label_concurrency=settings.openai_label_concurrency,
    )

    semaphore = _init_semaphore(settings.drive_product_enumerate_concurrency)

    sdk = importlib.import_module("heimdex_worker_sdk")
    queue_client = sdk.build_queue_client("product_enumerate", settings)
    consumer = sdk.ConsumerLoop(
        sqs_client=queue_client,
        process_callback=_make_callback(settings, vlm_client),
        semaphore=semaphore,
        visibility_timeout=settings.worker_lease_seconds,
        heartbeat_interval=300,
        worker_name="product_enumerate",
    )
    consumer.start()

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
            consumer.stop(timeout=30.0)
            stop_event.set()

        loop.add_signal_handler(signal.SIGTERM, shutdown)
        loop.add_signal_handler(signal.SIGINT, shutdown)
        log.info("enumerate_worker_started")
        emit_event(
            service=_SERVICE_NAME,
            event_name="worker_started",
            category="worker_lifecycle",
            level="INFO",
            metadata={
                "siglip2_model": settings.siglip2_model_id,
                "owlv2_model": settings.owlv2_model_id,
                "openai_model": settings.openai_model,
                "gpu": gpu_available,
            },
        )
        await stop_event.wait()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
