"""
GPU Worker Orchestrator — automatic start/stop of Aircloud+ GPU containers.

Two integration points:
  1. ensure_running(job_type) — called from sqs_producer._publish() after every
     SQS message.  Debounced: skips if the same worker was woken within
     AIRCLOUD_WAKE_DEBOUNCE_SECONDS (default 5 min).  Fire-and-forget.

   2. check_and_manage() — called every 5 min by APScheduler in drive-worker.
     Polls SQS queue depths, stops workers whose queues have been empty for
     AIRCLOUD_COOLDOWN_CHECKS consecutive checks (default 3 = 15 min).
     Also restarts workers that have queued messages but zero in-flight
     (stalled: worker stopped while messages remain).

Design principles:
  - Never block ingest or API requests.  All Aircloud calls are best-effort.
  - Idempotent: calling start on an already-running worker is a harmless no-op.
  - Stateless across restarts: cooldown counters reset (safe — worst case is
    one extra 5-min cycle before shutdown).
  - No new dependencies: uses boto3 (already present) + requests (already present).
"""

import logging
import threading
import time
from typing import Any, Optional

import boto3

from heimdex_worker_sdk.aircloud_client import AircloudClient

logger = logging.getLogger(__name__)


# ── Job type → SQS queue URL setting attr mapping ─────────────────────
# Mirrors sqs_producer._QUEUE_URL_ATTRS but only for GPU workers.
_GPU_JOB_TYPES = {
    "transcode": "sqs_transcode_queue_url",
    "caption": "sqs_caption_queue_url",
    "stt": "sqs_stt_queue_url",
    "ocr": "sqs_ocr_queue_url",
    "face": "sqs_face_queue_url",
    "visual_embed": "sqs_visual_embed_queue_url",
}

# Also map "processing" and "resplit" jobs to the transcode worker
# because processing → transcode is the first GPU step.
_JOB_TYPE_TO_WORKER = {
    "transcode": "transcode",
    "caption": "caption",
    "stt": "stt",
    "ocr": "ocr",
    "face": "face",
    "visual_embed": "visual_embed",
    # Processing/resplit jobs go to the drive-worker (EC2), but the
    # downstream transcode is GPU.  We wake transcode proactively.
    "processing": "transcode",
    "resplit": "transcode",
}


class GPUOrchestrator:
    """Manages Aircloud+ GPU worker lifecycle based on SQS queue depth.

    Args:
        aircloud_client: Configured AircloudClient instance.
        endpoint_map: Maps worker name → Aircloud endpoint UUID.
            Example: {"transcode": "feb226ed-...", "caption": "b8d5792e-..."}
        queue_url_map: Maps worker name → SQS queue URL.
            Example: {"transcode": "https://sqs.../livenow-transcode-queue"}
        sqs_region: AWS region for SQS API calls.
        wake_debounce_seconds: Minimum interval between wake-up calls per worker.
        cooldown_checks: Number of consecutive empty checks before stopping.
    """

    def __init__(
        self,
        aircloud_client: AircloudClient,
        endpoint_map: dict[str, str],
        queue_url_map: dict[str, str],
        sqs_region: str = "ap-northeast-2",
        wake_debounce_seconds: int = 300,
        cooldown_checks: int = 3,
    ) -> None:
        self._aircloud = aircloud_client
        self._endpoint_map = endpoint_map
        self._queue_url_map = queue_url_map
        self._sqs_region = sqs_region
        self._wake_debounce_seconds = wake_debounce_seconds
        self._cooldown_checks = cooldown_checks

        # Debounce state: worker_name → last wake-up timestamp
        self._last_wake: dict[str, float] = {}
        self._wake_lock = threading.Lock()

        # Cooldown state: worker_name → consecutive empty check count
        self._empty_counts: dict[str, int] = {}

    # ── Proactive wake-up (called from sqs_producer) ──────────────

    def ensure_running(self, job_type: str) -> None:
        """Ensure the GPU worker for this job type is running.

        Fire-and-forget: never raises, never blocks.
        Debounced: skips if called within wake_debounce_seconds for same worker.
        """
        worker_name = _JOB_TYPE_TO_WORKER.get(job_type)
        if worker_name is None:
            return

        endpoint_id = self._endpoint_map.get(worker_name)
        if not endpoint_id:
            return

        now = time.monotonic()
        with self._wake_lock:
            last = self._last_wake.get(worker_name, 0.0)
            if now - last < self._wake_debounce_seconds:
                return  # Debounced — skip
            self._last_wake[worker_name] = now

        # Reset cooldown counter — this worker has active work
        self._empty_counts[worker_name] = 0

        try:
            self._aircloud.start(endpoint_id)
        except Exception:
            logger.exception(
                "gpu_orchestrator_wake_failed",
                extra={"worker": worker_name, "endpoint_id": endpoint_id},
            )

    # ── Reactive shutdown (called by APScheduler every 5 min) ─────

    def check_and_manage(self) -> None:
        """Poll SQS queue depths and stop idle workers.

        Called periodically (every 5 min) by APScheduler in drive-worker.
        """
        queue_depths = self._poll_all_queue_depths()

        for worker_name, endpoint_id in self._endpoint_map.items():
            if not endpoint_id:
                continue

            queue_url = self._queue_url_map.get(worker_name, "")
            if not queue_url:
                continue

            depth = queue_depths.get(worker_name)
            if depth is None:
                # Failed to query — skip this worker, don't act on bad data
                continue

            waiting = depth["waiting"]
            in_flight = depth["in_flight"]
            total = waiting + in_flight

            if total > 0:
                # Work exists — reset cooldown
                self._empty_counts[worker_name] = 0

                if waiting > 0 and in_flight == 0:
                    # Messages queued but nothing in-flight — worker is
                    # likely stopped.  Restart it.  The sqs_producer's
                    # ensure_running only fires on NEW publishes; if all
                    # messages were published in a batch and the worker
                    # stopped (crash, Aircloud timeout, brief empty window),
                    # no new publishes will trigger a wake-up.
                    #
                    # Aircloud start is idempotent — calling it on an
                    # already-running worker is a harmless no-op.
                    try:
                        self._aircloud.start(endpoint_id)
                        logger.info(
                            "gpu_orchestrator_restarting_stalled_worker",
                            extra={
                                "worker": worker_name,
                                "endpoint_id": endpoint_id,
                                "waiting": waiting,
                            },
                        )
                    except Exception:
                        logger.exception(
                            "gpu_orchestrator_restart_failed",
                            extra={
                                "worker": worker_name,
                                "endpoint_id": endpoint_id,
                                "waiting": waiting,
                            },
                        )

                logger.info(
                    "gpu_orchestrator_worker_active",
                    extra={
                        "worker": worker_name,
                        "waiting": waiting,
                        "in_flight": in_flight,
                    },
                )
            else:
                # Queue empty — increment cooldown counter
                count = self._empty_counts.get(worker_name, 0) + 1
                self._empty_counts[worker_name] = count

                if count >= self._cooldown_checks:
                    # Cooldown reached — stop worker
                    logger.info(
                        "gpu_orchestrator_stopping_idle_worker",
                        extra={
                            "worker": worker_name,
                            "endpoint_id": endpoint_id,
                            "empty_checks": count,
                        },
                    )
                    try:
                        self._aircloud.stop(endpoint_id)
                    except Exception:
                        logger.exception(
                            "gpu_orchestrator_stop_failed",
                            extra={"worker": worker_name},
                        )
                else:
                    logger.info(
                        "gpu_orchestrator_worker_idle",
                        extra={
                            "worker": worker_name,
                            "empty_checks": count,
                            "cooldown_threshold": self._cooldown_checks,
                        },
                    )

    # ── SQS depth polling ─────────────────────────────────────────

    def _poll_all_queue_depths(self) -> dict[str, dict[str, int]]:
        """Query SQS for approximate message counts on all GPU queues.

        Returns: {worker_name: {"waiting": N, "in_flight": N}} for each
        worker.  Missing entries indicate query failure.
        """
        result: dict[str, dict[str, int]] = {}

        try:
            sqs_client = boto3.client("sqs", region_name=self._sqs_region)
        except Exception:
            logger.exception("gpu_orchestrator_sqs_client_failed")
            return result

        for worker_name, queue_url in self._queue_url_map.items():
            if not queue_url:
                continue
            try:
                resp = sqs_client.get_queue_attributes(
                    QueueUrl=queue_url,
                    AttributeNames=[
                        "ApproximateNumberOfMessages",
                        "ApproximateNumberOfMessagesNotVisible",
                    ],
                )
                attrs = resp.get("Attributes", {})
                result[worker_name] = {
                    "waiting": int(attrs.get("ApproximateNumberOfMessages", 0)),
                    "in_flight": int(
                        attrs.get("ApproximateNumberOfMessagesNotVisible", 0)
                    ),
                }
            except Exception:
                logger.exception(
                    "gpu_orchestrator_queue_depth_failed",
                    extra={"worker": worker_name, "queue_url": queue_url},
                )

        return result


# ── Module-level singleton (lazy init) ────────────────────────────────
#
# The API process and drive-worker process each get their own instance.
# Initialized on first call to get_orchestrator() or ensure_worker_running().

_orchestrator: Optional[GPUOrchestrator] = None
_init_lock = threading.Lock()


def _build_orchestrator_from_settings() -> Optional[GPUOrchestrator]:
    """Build a GPUOrchestrator from environment settings.

    Tries API settings first (for the FastAPI process), falls back to
    worker settings (for drive-worker).  Returns None if disabled.
    """
    # Try API settings
    try:
        from app.config import get_settings
        settings = get_settings()
    except ImportError:
        # Not running inside the API — try worker settings
        try:
            from heimdex_worker_sdk.settings import get_worker_settings
            settings = get_worker_settings()
        except Exception:
            return None

    if not getattr(settings, "aircloud_enabled", False):
        return None

    api_key = getattr(settings, "aircloud_api_key", "")
    if not api_key:
        logger.warning("gpu_orchestrator_disabled_no_api_key")
        return None

    aircloud = AircloudClient(api_key=api_key)

    endpoint_map: dict[str, str] = {}
    queue_url_map: dict[str, str] = {}

    for worker_name, queue_attr in _GPU_JOB_TYPES.items():
        ep_attr = f"aircloud_endpoint_{worker_name}"
        ep_id = getattr(settings, ep_attr, "")
        if ep_id:
            endpoint_map[worker_name] = ep_id

        queue_url = getattr(settings, queue_attr, "")
        if queue_url:
            queue_url_map[worker_name] = queue_url

    if not endpoint_map:
        logger.warning("gpu_orchestrator_disabled_no_endpoints")
        return None

    sqs_region = getattr(settings, "sqs_region", "ap-northeast-2")
    wake_debounce = getattr(settings, "aircloud_wake_debounce_seconds", 300)
    cooldown = getattr(settings, "aircloud_cooldown_checks", 3)

    logger.info(
        "gpu_orchestrator_initialized",
        extra={
            "endpoints": list(endpoint_map.keys()),
            "wake_debounce": wake_debounce,
            "cooldown_checks": cooldown,
        },
    )

    return GPUOrchestrator(
        aircloud_client=aircloud,
        endpoint_map=endpoint_map,
        queue_url_map=queue_url_map,
        sqs_region=sqs_region,
        wake_debounce_seconds=wake_debounce,
        cooldown_checks=cooldown,
    )


def get_orchestrator() -> Optional[GPUOrchestrator]:
    """Get or create the module-level GPUOrchestrator singleton.

    Returns None if Aircloud orchestration is disabled (AIRCLOUD_ENABLED=false
    or missing API key / endpoint IDs).
    """
    global _orchestrator
    if _orchestrator is not None:
        return _orchestrator

    with _init_lock:
        if _orchestrator is not None:
            return _orchestrator
        _orchestrator = _build_orchestrator_from_settings()
        return _orchestrator


def ensure_worker_running(job_type: str) -> None:
    """Convenience function for sqs_producer to call.

    Fire-and-forget: never raises, never blocks ingest.
    No-op if orchestrator is disabled.
    """
    try:
        orch = get_orchestrator()
        if orch is not None:
            orch.ensure_running(job_type)
    except Exception:
        # Absolute last resort — never let Aircloud issues affect ingest
        logger.exception(
            "gpu_orchestrator_ensure_running_unexpected",
            extra={"job_type": job_type},
        )
