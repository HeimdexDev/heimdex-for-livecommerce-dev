"""
Adapters that convert SQS message bodies into typed dataclasses so existing
task functions work unchanged.

v1 messages (per-video): converted to ``ClaimedFile`` for enrichment workers
  that process entire videos (STT, OCR, face, and legacy caption/visual-embed).
v2 messages (per-scene): converted to ``SceneJob`` for workers that process
  individual scenes (caption, visual-embed after Phase 2 deployment).

The SQS producer (``sqs_producer.py`` in the API) publishes both v1 and v2
messages. Workers dispatch to the appropriate handler based on message version.

See ``docs/PIPELINE_SCENE_SPLIT_PLAN.md`` for architecture details.
"""

import logging
from dataclasses import dataclass
from uuid import UUID

from heimdex_worker_sdk.internal_api import ClaimedFile, ClaimedProcessingFile
from heimdex_worker_sdk.sqs_client import SQSMessage
from heimdex_worker_sdk.sqs_consumer import InvalidMessageError


@dataclass(frozen=True)
class SceneJob:
    """Represents a single-scene enrichment job from a v2 SQS message.

    Unlike ``ClaimedFile`` (per-video), this provides a direct S3 key for one
    keyframe and the ``scene_id`` to target for the enrich API call.
    No manifest download needed — the message carries everything.
    """

    file_id: UUID
    org_id: UUID
    video_id: str
    scene_id: str
    scene_index: int
    keyframe_s3_key: str
    audio_s3_key: str | None = None
    transcript_raw: str | None = None
    vlm_tags_enabled: bool = False

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


def get_message_version(message: SQSMessage) -> str:
    """Extract the message version from an SQS message body.

    Returns ``"1"`` for legacy per-video messages (default),
    ``"2"`` for per-scene messages.
    """
    return message.body.get("version", "1")


def sqs_to_scene_job(message: SQSMessage) -> SceneJob:
    """Convert a v2 per-scene SQS message to ``SceneJob``.

    v2 messages carry a direct keyframe S3 key and scene_id, eliminating
    the need to download and parse the scene manifest.

    Raises:
        InvalidMessageError: If required fields are missing or malformed.
    """
    body = message.body
    try:
        return SceneJob(
            file_id=UUID(body["file_id"]),
            org_id=UUID(body["org_id"]),
            video_id=body["video_id"],
            scene_id=body["scene_id"],
            scene_index=body.get("scene_index", 0),
            keyframe_s3_key=body["keyframe_s3_key"],
            audio_s3_key=body.get("audio_s3_key"),
            transcript_raw=body.get("transcript_raw"),
            vlm_tags_enabled=bool(body.get("vlm_tags_enabled", False)),
        )
    except (KeyError, ValueError, TypeError) as e:
        raise InvalidMessageError(
            f"Cannot parse v2 scene message {message.message_id}: {e}"
        ) from e