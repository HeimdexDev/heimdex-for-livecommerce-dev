"""
Internal worker events router.

Endpoint allows workers to emit observability events over HTTP.
The event is persisted asynchronously via record_worker_event() — the request
returns immediately so workers never block on observability writes.

POST /internal/worker-events — Ingest a single worker event.

Auth: Pre-shared internal API key (Bearer token) via DRIVE_INTERNAL_API_KEY.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status as http_status

from app.dependencies import verify_internal_token
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
    _token: str = Depends(verify_internal_token),
) -> WorkerEventIngestResponse:
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
