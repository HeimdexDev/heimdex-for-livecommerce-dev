"""Per-message dispatcher.

Routes by the message ``type`` field. Track-worker handles
``product.track_job`` only; ``product.enumerate_job`` is the other
worker's responsibility.

Wraps :func:`handle_track_job` with a top-level catch so an unhandled
exception is reported back to the API as ``internal_error`` rather
than dying silently in the queue consumer + auto-failing on lease
expiry (which would surface to users only after a 30-min wait).
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from src.api_client import ApiClient
from src.settings import WorkerSettings
from src.tasks.track import handle_track_job

logger = logging.getLogger(__name__)


def dispatch(
    message: dict[str, Any] | str,
    *,
    settings: WorkerSettings,
) -> None:
    if isinstance(message, str):
        try:
            body = json.loads(message)
        except json.JSONDecodeError:
            logger.exception("dispatch_non_json_body", extra={"raw": message[:200]})
            return
    else:
        body = message

    msg_type = body.get("type")
    if msg_type == "product.track_job":
        try:
            handle_track_job(message=body, settings=settings)
        except Exception as exc:
            logger.exception("dispatch_unhandled_error")
            _try_fail_callback(
                body=body, settings=settings, error_message=str(exc),
            )
    else:
        logger.warning(
            "dispatch_unknown_type",
            extra={"type": msg_type, "job_id": body.get("job_id")},
        )


def _try_fail_callback(
    *,
    body: dict[str, Any],
    settings: WorkerSettings,
    error_message: str,
) -> None:
    """Best-effort fail report. Swallows HTTP errors at this layer —
    SQS will DLQ the message after maxReceiveCount=3 anyway."""
    try:
        job_id = UUID(str(body.get("job_id")))
    except Exception:
        return
    api = ApiClient(
        base_url=str(body.get("callback_base_url") or settings.drive_api_base_url),
        internal_api_key=settings.drive_internal_api_key,
        service_id=settings.internal_service_id,
    )
    try:
        api.fail(
            job_id=job_id,
            claimed_by=settings.worker_id,
            cost_delta_usd=Decimal("0"),
            error_code="internal_error",
            error_message=error_message[:1900],
        )
    except Exception:
        logger.exception("fail_callback_itself_failed", extra={"job_id": str(job_id)})
    finally:
        api.close()
