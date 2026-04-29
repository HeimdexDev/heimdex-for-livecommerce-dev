"""Per-message dispatcher.

Routes by the message ``type`` field. v1 only handles
``product.enumerate_job``; the track worker handles
``product.track_job`` independently.

Wraps :func:`handle_enumerate_job` with structured logging + a
top-level catch so an unhandled exception is reported back to the
API as ``internal_error`` rather than just dying silently in the
queue consumer.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from src.api_client import ApiClient
from src.openai_vlm import OpenAIVlmClient
from src.settings import WorkerSettings
from src.tasks.enumerate import handle_enumerate_job

logger = logging.getLogger(__name__)


def dispatch(
    message: dict[str, Any] | str,
    *,
    settings: WorkerSettings,
    vlm_client: OpenAIVlmClient,
) -> None:
    """Entry point for the ConsumerLoop callback.

    ``message`` may arrive as a parsed dict (worker-sdk) or a JSON
    string (legacy paths). Normalize both before routing.
    """
    if isinstance(message, str):
        try:
            body = json.loads(message)
        except json.JSONDecodeError:
            logger.exception("dispatch_non_json_body", extra={"raw": message[:200]})
            return
    else:
        body = message

    msg_type = body.get("type")
    if msg_type == "product.enumerate_job":
        try:
            handle_enumerate_job(
                message=body, settings=settings, vlm_client=vlm_client,
            )
        except Exception as exc:
            # Last-ditch failure callback. We try to attribute the
            # error to the job so the user-facing UI surfaces it
            # instead of the job hanging in ``enumerating`` until the
            # lease expires.
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
    """Best-effort fail report. Swallows any HTTP error — at this point
    the SQS message will go to the DLQ after maxReceiveCount=3 anyway."""
    try:
        job_id = UUID(str(body.get("job_id")))
    except Exception:
        return
    api = ApiClient(
        base_url=str(body.get("callback_base_url") or settings.drive_api_base_url),
        internal_api_key=settings.drive_internal_api_key,
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
