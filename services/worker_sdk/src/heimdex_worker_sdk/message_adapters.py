"""
Adapters that convert SQS message bodies into the same dataclasses used by
the HTTP polling path, so existing task functions work unchanged.

The SQS producer (``sqs_producer.py`` in the API) publishes messages whose
body fields are a superset of what ``ClaimedFile`` and ``ClaimedProcessingFile``
need.  These adapters extract the relevant fields and set ``lease_token=None``
because the SQS receipt handle serves as the lease in the SQS path.

See ``docs/queue_arch/02_message_contracts.md`` for full message schemas.
"""

import logging
from uuid import UUID

from heimdex_worker_sdk.internal_api import ClaimedFile, ClaimedProcessingFile
from heimdex_worker_sdk.sqs_client import SQSMessage
from heimdex_worker_sdk.sqs_consumer import InvalidMessageError

logger = logging.getLogger(__name__)


def sqs_to_claimed_file(message: SQSMessage) -> ClaimedFile:
    """Convert an enrichment SQS message to ``ClaimedFile``.

    Works for caption, stt, and ocr queue messages.  The returned
    ``ClaimedFile`` has ``lease_token=None`` because the SQS receipt
    handle replaces the HTTP-based lease.

    Raises:
        InvalidMessageError: If required fields are missing or malformed.
    """
    body = message.body
    try:
        return ClaimedFile(
            id=UUID(body["file_id"]),
            org_id=UUID(body["org_id"]),
            video_id=body["video_id"],
            keyframe_s3_prefix=body.get("keyframe_s3_prefix"),
            audio_s3_key=body.get("audio_s3_key"),
            lease_token=None,
        )
    except (KeyError, ValueError, TypeError) as e:
        raise InvalidMessageError(
            f"Cannot parse enrichment message {message.message_id}: {e}"
        ) from e


def sqs_to_claimed_processing_file(message: SQSMessage) -> ClaimedProcessingFile:
    """Convert a processing SQS message to ``ClaimedProcessingFile``.

    Raises:
        InvalidMessageError: If required fields are missing or malformed.
    """
    body = message.body
    try:
        return ClaimedProcessingFile(
            id=UUID(body["file_id"]),
            org_id=UUID(body["org_id"]),
            connection_id=UUID(body["connection_id"]),
            google_file_id=body["google_file_id"],
            file_name=body["file_name"],
            video_id=body["video_id"],
            mime_type=body["mime_type"],
            file_size_bytes=body.get("file_size_bytes"),
            library_id=UUID(body["library_id"]) if body.get("library_id") else None,
            scope_type=body.get("scope_type"),
            drive_id=body.get("drive_id"),
            google_created_time=body.get("google_created_time"),
            google_modified_time=body.get("google_modified_time"),
            lease_token=None,
        )
    except (KeyError, ValueError, TypeError) as e:
        raise InvalidMessageError(
            f"Cannot parse processing message {message.message_id}: {e}"
        ) from e
