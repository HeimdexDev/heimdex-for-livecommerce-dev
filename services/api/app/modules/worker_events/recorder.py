from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from app.logging_config import get_logger

from .schemas import WorkerEventCategory, WorkerEventLevel

logger = get_logger(__name__)

# Caps concurrent DB sessions held for event recording. The asyncpg pool is
# small (~10) and shared with user-facing request handlers; without this gate
# an event burst (workers fire ~4 events/job × N concurrent jobs) raced with
# real traffic and could exhaust the pool.
_RECORDER_SEMAPHORE = asyncio.Semaphore(20)


async def _record_worker_event(
    *,
    service: str,
    event_name: str,
    category: WorkerEventCategory,
    level: WorkerEventLevel,
    org_id: UUID | None,
    job_id: UUID | None,
    video_id: UUID | None,
    duration_ms: int | None,
    message: str | None,
    metadata: dict[str, Any] | None,
) -> None:
    """Fire-and-forget worker event recording.

    Creates its own short-lived DB session — the caller's session may already
    be closed by the time this background task runs.
    Failures are logged and swallowed — observability must never block work.
    """
    try:
        async with _RECORDER_SEMAPHORE:
            from app.db.base import get_async_session_factory

            from .repository import WorkerEventRepository

            factory = get_async_session_factory()
            async with factory() as session:
                repo = WorkerEventRepository(session)
                await repo.create(
                    service=service,
                    event_name=event_name,
                    category=category,
                    level=level,
                    org_id=org_id,
                    job_id=job_id,
                    video_id=video_id,
                    duration_ms=duration_ms,
                    message=message,
                    metadata=metadata,
                )
                await session.commit()
    except Exception:
        logger.warning("worker_event_recording_failed", exc_info=True)


def record_worker_event(
    *,
    service: str,
    event_name: str,
    category: WorkerEventCategory,
    level: WorkerEventLevel,
    org_id: UUID | None = None,
    job_id: UUID | None = None,
    video_id: UUID | None = None,
    duration_ms: int | None = None,
    message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> asyncio.Task[None] | None:
    """Schedule a worker event write as a background task.

    Returns the Task so callers can await/cancel if needed; most call sites
    fire and forget.  Returns ``None`` when recording is disabled via
    ``settings.analytics_enabled=False`` (shared kill switch with search events).
    """
    from app.config import get_settings

    if not get_settings().analytics_enabled:
        return None

    return asyncio.create_task(
        _record_worker_event(
            service=service,
            event_name=event_name,
            category=category,
            level=level,
            org_id=org_id,
            job_id=job_id,
            video_id=video_id,
            duration_ms=duration_ms,
            message=message,
            metadata=metadata,
        )
    )
