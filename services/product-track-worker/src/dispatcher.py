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

import httpx
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
            fail_recorded = _try_fail_callback(
                body=body, settings=settings, error_message=str(exc),
            )
            if not fail_recorded:
                # The api call itself failed (5xx / timeout / network).
                # Re-raising leaves the SQS message visible so it's
                # redelivered after the visibility timeout — eventually
                # DLQ'd if the api stays down. Pre-fix this swallowed
                # the second failure and the SDK ack-deleted the
                # message, leaving the job stuck in ``tracking`` with
                # no retry path.
                raise
        return

    # F2: unknown type. Two sub-cases:
    #
    # * Body carries a parseable ``job_id`` (real api-enqueued row
    #   that landed on the wrong queue): re-raise a generic
    #   ``DispatchUnknownTypeError`` so the SDK leaves the message
    #   visible. SQS redelivery → eventual DLQ → operator alert.
    #   Ack-deleting via ``InvalidMessageError`` would orphan the
    #   ``ProductScanJob`` row at ``queued/in_progress`` forever
    #   (this worker can't /fail it without owning the lease, and
    #   no api-side cleanup path exists for queued rows).
    # * Body lacks a parseable ``job_id`` (truly malformed —
    #   manual injection, schema drift, garbage in the queue):
    #   ``InvalidMessageError`` poison-pill is correct, no api row
    #   to orphan.
    job_id_raw = body.get("job_id")
    try:
        UUID(str(job_id_raw))
        has_real_job_id = True
    except Exception:
        has_real_job_id = False

    logger.warning(
        "dispatch_unknown_type",
        extra={
            "type": msg_type,
            "job_id": job_id_raw,
            "has_real_job_id": has_real_job_id,
        },
    )

    if not has_real_job_id:
        raise InvalidMessageError(
            f"unknown message type {msg_type!r} on track queue, no parseable job_id"
        )

    # Real job that we can't process here. Surface to DLQ so an
    # operator fixes the routing and re-enqueues to the right
    # worker's queue.
    raise DispatchUnknownTypeError(
        f"refusing to process {msg_type!r} on track queue — "
        f"job_id={job_id_raw}; expected on enumerate queue. "
        f"Will redeliver until DLQ for operator triage."
    )


class DispatchUnknownTypeError(RuntimeError):
    """Raised when a real (job_id-bearing) message lands on the
    wrong worker's queue. NOT a poison pill — the SDK's normal
    exception path lets SQS redeliver, eventually DLQ for operator
    triage. Distinct from ``InvalidMessageError`` (which ack-deletes
    immediately).
    """


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
) -> bool:
    """Best-effort fail report. Returns True if the api accepted the
    /fail call, False otherwise (so the caller can decide to re-raise
    and let SQS redeliver). When the body has no parseable job_id we
    return True — there's nothing to record on the api side and the
    caller should NOT redeliver."""
    try:
        job_id = UUID(str(body.get("job_id")))
    except Exception:
        return True
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
        return True
    except httpx.HTTPStatusError as exc:
        # 409 from /fail = "lease lost or job missing" (per
        # internal_router._FailRequest handler). The job is already
        # in a terminal state on the api side; redelivering the SQS
        # message can't help. Treat as success so the caller
        # ack-deletes instead of re-raising into DLQ retry.
        if exc.response.status_code == 409:
            logger.info(
                "fail_callback_409_terminal_state",
                extra={
                    "job_id": str(job_id),
                    "note": (
                        "lease lost or job missing — message ack-deleted, "
                        "no SQS redelivery needed"
                    ),
                },
            )
            return True
        logger.exception("fail_callback_itself_failed", extra={"job_id": str(job_id)})
        return False
    except Exception:
        logger.exception("fail_callback_itself_failed", extra={"job_id": str(job_id)})
        return False
    finally:
        api.close()
