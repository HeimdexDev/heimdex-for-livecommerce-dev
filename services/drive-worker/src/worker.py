import asyncio
import logging
import shutil
import signal
import threading
from collections import defaultdict
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from heimdex_worker_sdk.internal_api import InternalAPIClient

from heimdex_worker_sdk.settings import get_worker_settings
from src.tasks.discover import discover_new_files

logger = logging.getLogger(__name__)

_org_slots: dict[str, int] = defaultdict(int)
_org_lock = threading.Lock()

# Global concurrency semaphore — acquired by SQS consumer for backpressure control.
_global_semaphore: Optional[threading.Semaphore] = None


def _init_semaphore(max_concurrent: int) -> threading.Semaphore:
    global _global_semaphore
    if _global_semaphore is None:
        _global_semaphore = threading.Semaphore(max_concurrent)
    return _global_semaphore


def _check_disk_budget(temp_dir: Path, budget_gb: float) -> bool:
    if not temp_dir.exists():
        return True
    usage = shutil.disk_usage(temp_dir)
    used_gb = (usage.total - usage.free) / (1024 ** 3)
    return used_gb < budget_gb


async def poll_and_discover(api_client: InternalAPIClient) -> None:
    """Periodic discovery of new files from Google Drive.

    Processing is handled exclusively by the SQS consumer (Phase 3).
    This poll loop only syncs Google Drive connections to find new files.
    """
    settings = get_worker_settings()

    if not settings.drive_connector_enabled:
        return

    temp_dir = Path(settings.drive_temp_dir)
    if not _check_disk_budget(temp_dir, settings.drive_temp_disk_budget_gb):
        logger.warning("disk_budget_exceeded", extra={"temp_dir": str(temp_dir), "budget_gb": settings.drive_temp_disk_budget_gb})
        return

    try:
        discovered_count = discover_new_files(api_client=api_client, settings=settings)
        if discovered_count:
            logger.info("drive_discovery_complete", extra={"discovered_count": discovered_count})
    except Exception:
        logger.exception("discovery_cycle_failed")


def _make_sqs_callback(api_client, settings):
    """Create the SQS message callback for processing.
    The SQS message is treated as a wake-up signal.  On receipt the callback
    claims the file via the HTTP API (which issues a lease_token via atomic
    SKIP LOCKED) and then calls ``_process_single_file`` with the properly
    claimed file.  This guarantees the same lease semantics used by all API
    endpoints (status updates, token broker, etc.).
    """
    from heimdex_worker_sdk.message_adapters import sqs_to_claimed_processing_file
    from src.tasks.process import _process_single_file

    def callback(message):
        # Parse message for org_id (used for per-org concurrency check only)
        sqs_file = sqs_to_claimed_processing_file(message)
        org_id_str = str(sqs_file.org_id)
        # Per-org concurrency check (global semaphore already held by SQSConsumerLoop)
        with _org_lock:
            if _org_slots[org_id_str] >= settings.drive_worker_per_org_concurrency:
                logger.info(
                    "sqs_processing_per_org_limit",
                    extra={"org_id": org_id_str, "file_id": str(sqs_file.id)},
                )
                # Raise to trigger SQS redelivery after visibility timeout
                raise RuntimeError(f"Per-org concurrency limit reached for {org_id_str}")
            _org_slots[org_id_str] += 1
        try:
            # Claim the file via HTTP API to obtain a real lease_token.
            # The SQS message is just a notification; the API claim does the
            # atomic SKIP LOCKED and assigns a lease that status-update and
            # token-broker endpoints require.
            claimed_files = api_client.claim_processing(limit=1)
            if not claimed_files:
                logger.info(
                    "sqs_no_claimable_file",
                    extra={"sqs_file_id": str(sqs_file.id), "org_id": org_id_str},
                )
                return

            claimed_file = claimed_files[0]
            logger.info(
                "sqs_file_claimed_via_api",
                extra={
                    "file_id": str(claimed_file.id),
                    "video_id": claimed_file.video_id,
                    "file_name": claimed_file.file_name,
                    "has_lease": claimed_file.lease_token is not None,
                },
            )
            _process_single_file(
                api_client=api_client,
                settings=settings,
                claimed_file=claimed_file,
            )
        finally:
            with _org_lock:
                _org_slots[org_id_str] = max(0, _org_slots[org_id_str] - 1)

    return callback


def main() -> None:
    settings = get_worker_settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if not settings.drive_connector_enabled:
        logger.info("drive_connector_disabled, worker sleeping indefinitely")
        signal.pause()
        return

    api_client = InternalAPIClient(
        base_url=settings.drive_api_base_url,
        api_key=settings.drive_internal_api_key,
    )

    temp_dir = Path(settings.drive_temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Initialize shared semaphore before starting any consumers
    semaphore = _init_semaphore(settings.drive_worker_global_concurrency)

    # ── SQS Consumer (primary job source for processing) ──────────
    # Only handles processing claims. Discovery stays HTTP-only.
    import sys
    if not settings.sqs_consumer_enabled or not settings.sqs_processing_queue_url:
        logger.error(
            "sqs_consumer_required",
            extra={"sqs_consumer_enabled": settings.sqs_consumer_enabled, "queue_url": bool(settings.sqs_processing_queue_url)},
        )
        sys.exit(1)

    from heimdex_worker_sdk.sqs_client import SQSJobClient
    from heimdex_worker_sdk.sqs_consumer import SQSConsumerLoop

    sqs_client = SQSJobClient(
        queue_url=settings.sqs_processing_queue_url,
        region=settings.sqs_region,
        endpoint_url=settings.sqs_endpoint_url or None,
    )
    sqs_consumer = SQSConsumerLoop(
        sqs_client=sqs_client,
        process_callback=_make_sqs_callback(api_client, settings),
        semaphore=semaphore,
        visibility_timeout=120,
        heartbeat_interval=80,
        worker_name="processing",
    )
    sqs_consumer.start()

    # ── SQS Consumer (export proxy-pack jobs) ─────────────────────
    export_consumer = None
    if settings.sqs_export_queue_url:
        from src.tasks.export import handle_export_proxy_pack

        def _export_callback(message):
            handle_export_proxy_pack(message.body, api_client, settings)

        export_sqs_client = SQSJobClient(
            queue_url=settings.sqs_export_queue_url,
            region=settings.sqs_region,
            endpoint_url=settings.sqs_endpoint_url or None,
        )
        export_consumer = SQSConsumerLoop(
            sqs_client=export_sqs_client,
            process_callback=_export_callback,
            semaphore=semaphore,
            visibility_timeout=600,
            heartbeat_interval=300,
            worker_name="export",
        )
        export_consumer.start()
        logger.info("export_sqs_consumer_started", extra={"queue_url": settings.sqs_export_queue_url})
    else:
        logger.info("export_sqs_consumer_disabled")

    # ── HTTP Poll (discovery only — no processing claims) ─────────
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        poll_and_discover,
        "interval",
        seconds=settings.drive_worker_poll_interval_seconds,
        args=[api_client],
        max_instances=1,
        id="drive_discovery_poll",
    )

    async def _run() -> None:
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()

        def shutdown(*_: object) -> None:
            logger.info("shutdown_signal_received")
            scheduler.shutdown(wait=False)
            sqs_consumer.stop(timeout=30.0)
            if export_consumer:
                export_consumer.stop(timeout=30.0)
            stop_event.set()

        loop.add_signal_handler(signal.SIGTERM, shutdown)
        loop.add_signal_handler(signal.SIGINT, shutdown)

        scheduler.start()
        logger.info(
            "drive_worker_started",
            extra={
                "discovery_poll_interval": settings.drive_worker_poll_interval_seconds,
                "global_concurrency": settings.drive_worker_global_concurrency,
                "per_org_concurrency": settings.drive_worker_per_org_concurrency,
                "disk_budget_gb": settings.drive_temp_disk_budget_gb,
                "sqs_consumer_enabled": settings.sqs_consumer_enabled,
            },
        )
        await stop_event.wait()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
