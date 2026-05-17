"""SQS message-type dispatcher for drive-blur-worker.

One queue, two message types. The dispatcher sniffs the ``type`` field
on the parsed body and routes to the appropriate task handler:

* ``blur.job_created``   → :mod:`src.tasks.blur_video`
* ``blur.export_created`` → :mod:`src.tasks.export_layer`

Anything else raises ``UnknownMessageType`` so the SQS consumer loop's
built-in error handling treats it as a poison message and routes it
to the DLQ after the max-receive count.

Loose coupling: the dispatcher imports neither task module at the
top; handlers are loaded lazily on first route so unit tests for the
routing layer don't pay the cost of loading torch + transformers (via
``tasks.blur_video`` → ``heimdex_media_pipelines.blur``).
"""

from __future__ import annotations

import importlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


# Mirrors heimdex_media_contracts.blur.BLUR_JOB_CREATED_TYPE etc. We
# hardcode string literals here (instead of importing from contracts)
# so the dispatcher has zero import-time dependencies and the
# unit-test harness can exercise routing without installing contracts
# in the test venv.
_TYPE_BLUR_JOB_CREATED = "blur.job_created"
_TYPE_BLUR_EXPORT_CREATED = "blur.export_created"


class UnknownMessageType(ValueError):
    """Raised when a message's ``type`` field is missing or unrecognised.

    Derives from ``ValueError`` so the SQS consumer's generic retry
    path marks the message as poison after the max-receive count.
    """


def _parse_body(message: Any) -> dict[str, Any]:
    body_raw = message.body if hasattr(message, "body") else message["Body"]
    if isinstance(body_raw, (bytes, bytearray)):
        body_raw = body_raw.decode("utf-8")
    if isinstance(body_raw, str):
        return json.loads(body_raw)
    return body_raw


def message_type(message: Any) -> str:
    """Return the ``type`` field of an SQS message body, or raise."""
    body = _parse_body(message)
    msg_type = body.get("type")
    if not isinstance(msg_type, str):
        raise UnknownMessageType(
            f"message body has no string 'type' field: keys={list(body.keys())}"
        )
    return msg_type


def dispatch(
    message: Any,
    *,
    api_base_url: str,
    internal_api_key: str,
    settings: Any,
    pipeline: Any,
) -> None:
    """Route one SQS message to its task handler.

    ``pipeline`` is the warm :class:`BlurPipeline` singleton from
    :func:`src.worker._build_blur_pipeline` — only the blur-job handler
    uses it; the export handler is stateless and ignores this argument.
    We still thread it through so the dispatcher signature is uniform
    across message types.
    """
    msg_type = message_type(message)

    if msg_type == _TYPE_BLUR_JOB_CREATED:
        blur_video = importlib.import_module("src.tasks.blur_video")
        claim_ref = blur_video.sqs_to_blur_claim(message)
        blur_video.process_blur_message(
            api_base_url=api_base_url,
            internal_api_key=internal_api_key,
            settings=settings,
            claim_ref=claim_ref,
            pipeline=pipeline,
        )
        return

    if msg_type == _TYPE_BLUR_EXPORT_CREATED:
        export_layer = importlib.import_module("src.tasks.export_layer")
        export_ref = export_layer.sqs_to_export_ref(message)
        export_layer.process_export_message(
            api_base_url=api_base_url,
            internal_api_key=internal_api_key,
            settings=settings,
            export_ref=export_ref,
        )
        return

    logger.warning(
        "blur_dispatcher_unknown_type",
        extra={"type": msg_type},
    )
    raise UnknownMessageType(f"unknown message type {msg_type!r}")


__all__ = [
    "UnknownMessageType",
    "dispatch",
    "message_type",
]
