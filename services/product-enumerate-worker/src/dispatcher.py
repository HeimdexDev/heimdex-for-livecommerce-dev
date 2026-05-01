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

import httpx
from heimdex_worker_sdk.queue_client import QueueMessage
from heimdex_worker_sdk.sqs_consumer import InvalidMessageError

from src.api_client import ApiClient
from src.openai_vlm import OpenAIVlmClient
from src.settings import WorkerSettings
from src.tasks.enumerate import handle_enumerate_job

logger = logging.getLogger(__name__)


def dispatch(
    message: QueueMessage | dict[str, Any] | str,
    *,
    settings: WorkerSettings,
    vlm_client: OpenAIVlmClient,
) -> None:
    """Entry point for the SDK's ``ConsumerLoop`` callback.

    Accepts ``QueueMessage`` (current SDK type), ``dict`` (test harness
    shape), or ``str`` (raw JSON). F1 fix: previously assumed
    ``dict|str`` only and crashed on the SDK's actual ``QueueMessage``.

    F2 fix: malformed bodies + unknown ``type`` now route to either
    ``InvalidMessageError`` (poison pill, SDK deletes with structured
    log) or ``/fail`` on the api (so the user-facing UI surfaces the
    misrouting), instead of silently ack'ing without retry, DLQ, or
    error report.
    """
    body = _normalize_body(message)

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
            fail_recorded = _try_fail_callback(
                body=body, settings=settings, error_message=str(exc),
            )
            if not fail_recorded:
                # api outage — let SQS redeliver instead of silently
                # ack-deleting the message and orphaning the job.
                raise
        return

    # F2: unknown type — log + raise ``InvalidMessageError`` so the
    # SDK ack-deletes via poison-pill semantics
    # (``sqs_invalid_message_deleted`` structured log).
    #
    # We do NOT try to /fail the job here. The api's /fail requires
    # ``claimed_by`` to own the lease, but a misrouted message landed
    # here without this worker ever claiming — /fail would 409. The
    # row's actual owner (or the api's lease-expiry sweeper) is the
    # right authority.
    job_id_present = body.get("job_id") is not None
    logger.warning(
        "dispatch_unknown_type",
        extra={"type": msg_type, "job_id": body.get("job_id"), "has_job_id": job_id_present},
    )
    raise InvalidMessageError(
        f"unknown message type {msg_type!r} on enumerate queue "
        f"(job_id={'present' if job_id_present else 'absent'})"
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
) -> bool:
    """Best-effort fail report. Returns True if the api accepted the
    /fail call, False otherwise (so the caller can re-raise and let
    SQS redeliver). When the body has no parseable job_id we return
    True — there's nothing to record on the api side."""
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
        # 409 from /fail = "lease lost or job missing". The job is
        # already terminal on the api side; redelivering the SQS
        # message can't help. Ack-delete instead of re-raising.
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
