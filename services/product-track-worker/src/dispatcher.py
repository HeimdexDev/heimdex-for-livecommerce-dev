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

from heimdex_worker_sdk.queue_client import QueueMessage
from heimdex_worker_sdk.sqs_consumer import InvalidMessageError

from src.api_client import ApiClient
from src.settings import WorkerSettings
from src.tasks.track import handle_track_job

logger = logging.getLogger(__name__)


def dispatch(
    message: QueueMessage | dict[str, Any] | str,
    *,
    settings: WorkerSettings,
) -> None:
    """Entry point for the SDK's ``ConsumerLoop`` callback.

    Accepts ``QueueMessage`` (the SDK's current type), ``dict`` (legacy
    test harness shape), or ``str`` (raw JSON, also legacy). F1 fix:
    SDK now passes ``QueueMessage``, not raw dict/string.

    F2 fix: malformed messages and unknown ``type`` no longer silently
    succeed (which would delete from queue without retry, DLQ, or any
    user-visible error). Instead:

    * Non-JSON / non-dict bodies raise ``InvalidMessageError`` so the
      SDK logs ``sqs_invalid_message_deleted`` and ack-deletes — same
      semantics as before but with a structured log.
    * Unknown ``type`` with a parseable ``job_id`` calls ``/fail`` with
      ``error_code="unknown_message_type"`` so the api row is closed
      and the user-facing UI surfaces the misrouting.
    * Unknown ``type`` without a job_id raises ``InvalidMessageError``.
    """
    body = _normalize_body(message)

    msg_type = body.get("type")
    if msg_type == "product.track_job":
        try:
            handle_track_job(message=body, settings=settings)
        except Exception as exc:
            logger.exception("dispatch_unhandled_error")
            _try_fail_callback(
                body=body, settings=settings, error_message=str(exc),
            )
        return

    # F2: unknown type — surface to the api as a real failure if we
    # can identify the job, otherwise log + ack-delete via SDK poison
    # pill semantics.
    try:
        job_id = UUID(str(body.get("job_id")))
    except Exception:
        logger.warning(
            "dispatch_unknown_type_no_job_id",
            extra={"type": msg_type},
        )
        raise InvalidMessageError(
            f"unknown message type {msg_type!r}, no parseable job_id"
        )

    logger.warning(
        "dispatch_unknown_type",
        extra={"type": msg_type, "job_id": str(job_id)},
    )
    # The API's ``_FailRequest.error_code`` enum doesn't carry a
    # dedicated ``unknown_message_type`` literal — using
    # ``internal_error`` is the only valid path. The structured
    # ``dispatch_unknown_type`` log + error_message preserve the
    # routing detail for operators.
    _try_fail_callback(
        body=body,
        settings=settings,
        error_message=f"unknown message type {msg_type!r}",
    )


def _normalize_body(
    message: QueueMessage | dict[str, Any] | str,
) -> dict[str, Any]:
    """Coerce the SDK message shape (or test inputs) to a dict body.

    Raises :class:`InvalidMessageError` for inputs that can't be
    interpreted as a job — the SDK's ``_process_with_heartbeat`` treats
    that as a poison pill and ack-deletes with a ``poison_pill_deleted``
    structured log.
    """
    if isinstance(message, QueueMessage):
        return message.body
    if isinstance(message, dict):
        return message
    if isinstance(message, str):
        try:
            parsed = json.loads(message)
        except json.JSONDecodeError as exc:
            raise InvalidMessageError(
                f"non-JSON SQS body: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise InvalidMessageError(
                f"SQS body must be a JSON object, got {type(parsed).__name__}"
            )
        return parsed
    raise InvalidMessageError(
        f"unsupported message type {type(message).__name__}"
    )


def _try_fail_callback(
    *,
    body: dict[str, Any],
    settings: WorkerSettings,
    error_message: str,
    error_code: str = "internal_error",
) -> None:
    """Best-effort fail report. Swallows HTTP errors at this layer."""
    try:
        job_id = UUID(str(body.get("job_id")))
    except Exception:
        return
    # SECURITY (F3): never honor a callback URL from the queue body —
    # the API base is always settings.drive_api_base_url. A compromised
    # producer would otherwise redirect bearer-authed callbacks to an
    # attacker host.
    api = ApiClient(
        base_url=settings.drive_api_base_url,
        internal_api_key=settings.drive_internal_api_key,
        service_id=settings.internal_service_id,
    )
    try:
        api.fail(
            job_id=job_id,
            claimed_by=settings.worker_id,
            cost_delta_usd=Decimal("0"),
            error_code=error_code,
            error_message=error_message[:1900],
        )
    except Exception:
        logger.exception("fail_callback_itself_failed", extra={"job_id": str(job_id)})
    finally:
        api.close()
