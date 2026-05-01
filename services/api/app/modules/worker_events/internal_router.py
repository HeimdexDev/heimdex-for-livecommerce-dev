"""
Internal worker events router.

Endpoint allows workers to emit observability events over HTTP.
The event is persisted asynchronously via record_worker_event() — the request
returns immediately so workers never block on observability writes.

POST /internal/worker-events — Ingest a single worker event.

Auth (F1 Phase 3, post-2026-05-01): per-service token via
``verify_service_identity``. Workers send ``X-Heimdex-Service-Id``
header + their per-service token. Legacy global bearer continues
to work as a backward-compat fallback (returns
``service_id="legacy"``) so this PR doesn't require a simultaneous
worker rollout.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status as http_status

from app.lib.internal_auth import verify_service_identity
from app.logging_config import get_logger

from .internal_schemas import WorkerEventIngestRequest, WorkerEventIngestResponse
from .recorder import record_worker_event

logger = get_logger(__name__)

router = APIRouter(prefix="/internal/worker-events", tags=["internal-worker-events"])


@router.post(
    "",
    response_model=WorkerEventIngestResponse,
    status_code=http_status.HTTP_202_ACCEPTED,
)
async def ingest_worker_event(
    request: WorkerEventIngestRequest,
    verified_service_id: str = Depends(verify_service_identity),
) -> WorkerEventIngestResponse:
    """Ingest a worker observability event.

    The body's ``request.service`` is what the worker SAYS it is —
    self-asserted, not authenticated. ``verified_service_id`` is the
    api-validated identity used for audit. We log mismatches so a
    future investigation can spot a "service-A bearer claiming to be
    service-B in the body" attack pattern.
    """
    if (
        verified_service_id != "legacy"
        and verified_service_id != request.service
    ):
        # Body claim doesn't match the verified bearer. Log + still
        # accept — changing this to a 401 would block legitimate
        # workers whose body ``service`` field differs from their
        # api token's ``service_id`` (e.g., subsystems within a
        # worker, multi-component services). Tighten only after we
        # audit actual traffic.
        logger.warning(
            "worker_event_service_mismatch",
            verified_service_id=verified_service_id,
            body_service=request.service,
        )

    record_worker_event(
        service=request.service,
        event_name=request.event_name,
        category=request.category,
        level=request.level,
        org_id=request.org_id,
        job_id=request.job_id,
        video_id=request.video_id,
        duration_ms=request.duration_ms,
        message=request.message,
        metadata=request.metadata,
    )
    return WorkerEventIngestResponse(accepted=True)
