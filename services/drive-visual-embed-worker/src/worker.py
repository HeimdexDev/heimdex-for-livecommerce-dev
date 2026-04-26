"""SQS-driven visual embedding worker.

Consumes jobs from the visual-embed SQS queue, downloads keyframes from S3,
runs SigLIP2 vision encoder to produce 768-dim embeddings, and posts results
back to the API via /internal/ingest/enrich.

Architecture:
    SQS queue → SQSConsumerLoop → _process_single_visual_embed → enrich API

Follows the same pattern as drive-caption-worker and drive-stt-worker.
"""
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


def _make_sqs_callback(api_client, settings):
    """Create the SQS message callback for visual embedding processing.

    Dispatches to v1 (per-video) or v2 (per-scene) handler based on
    the message version field.  Backward-compatible: v1 messages from
    before Phase 2 deployment continue to work.
    """
    from heimdex_worker_sdk.message_adapters import (
        get_message_version,
        sqs_to_claimed_file,
        sqs_to_scene_job,
    )
    ve_mod = importlib.import_module("src.tasks.visual_embed")
    _process_single_visual_embed = ve_mod._process_single_visual_embed
    _process_single_scene_visual_embed = ve_mod._process_single_scene_visual_embed
    _process_single_scene_color_extract = ve_mod._process_single_scene_color_extract

    def callback(message):
        version = get_message_version(message)
        if version == "2":
            scene_job = sqs_to_scene_job(message)
            job_type = message.body.get("job_type", "visual_embed")
            if job_type == "color_extract":
                _process_single_scene_color_extract(
                    api_client=api_client,
                    settings=settings,
                    scene_job=scene_job,
                )
            else:
                _process_single_scene_visual_embed(
                    api_client=api_client,
                    settings=settings,
                    scene_job=scene_job,
                )
        else:
            claimed_file = sqs_to_claimed_file(message)
            _process_single_visual_embed(
                api_client=api_client,
                settings=settings,
                claimed_file=claimed_file,
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

    # Visual embed worker uses its own enabled flag
    visual_embed_enabled = getattr(settings, "visual_embed_enabled", False)
    if not visual_embed_enabled:
        logger.info("visual_embed_worker_disabled — set VISUAL_EMBED_ENABLED=true to enable")
        signal.pause()
        return

    api_client = InternalAPIClient(
        base_url=settings.drive_api_base_url,
        api_key=settings.drive_internal_api_key,
    )

    # Concurrency: default 1 (GPU-bound, not much benefit from parallelism)
    concurrency = getattr(settings, "visual_embed_concurrency", 1)
    semaphore = _init_semaphore(concurrency)

    # ── SQS Consumer (primary job source) ──────────────────────────────────────
    sqs_queue_url = getattr(settings, "sqs_visual_embed_queue_url", "")
    if settings.queue_backend == "rabbitmq":
        pass
    elif not getattr(settings, "sqs_consumer_enabled", False) or not sqs_queue_url:
        logger.error("sqs_consumer_required_but_not_configured", extra={"queue": "visual_embed"})
        sys.exit(1)

    from heimdex_worker_sdk import build_queue_client, ConsumerLoop

    queue_client = build_queue_client("visual_embed", settings)
    sqs_consumer = ConsumerLoop(
        sqs_client=queue_client,
        process_callback=_make_sqs_callback(api_client, settings),
        semaphore=semaphore,
        visibility_timeout=120,  # Longer than caption — embedding batches can take time
        heartbeat_interval=80,
        worker_name="visual_embed",
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
            "visual_embed_worker_started",
            extra={
                "concurrency": concurrency,
                "sqs_queue": sqs_queue_url,
                "use_gpu": getattr(settings, "use_gpu", False),
            },
        )
        await stop_event.wait()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
