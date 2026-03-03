"""
SQS dual-write producer for job creation events.

Phase 1: Publishes SQS messages alongside DB writes when sqs_enabled=true.
All sends are fire-and-forget with structured error logging.
DB operations are NEVER affected by SQS failures.

Trigger points:
  1. publish_processing_job()  — called from upsert_files() after new DriveFile created
  2. publish_enrichment_jobs() — called from update_processing_status() when status='indexed'
"""

import json
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Optional
from uuid import UUID

import boto3

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)


# ── Queue URL mapping ──────────────────────────────────────────────────

_QUEUE_URL_ATTRS = {
    "processing": "sqs_processing_queue_url",
    "caption": "sqs_caption_queue_url",
    "stt": "sqs_stt_queue_url",
    "ocr": "sqs_ocr_queue_url",
    "transcode": "sqs_transcode_queue_url",
    "face": "sqs_face_queue_url",
    "visual_embed": "sqs_visual_embed_queue_url",
    "export": "sqs_export_queue_url",
}

# ── Internal helpers ───────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_sqs_client():
    """Lazily create boto3 SQS client (cached singleton)."""
    settings = get_settings()
    kwargs: dict[str, Any] = {"region_name": settings.sqs_region}
    if settings.sqs_endpoint_url:
        kwargs["endpoint_url"] = settings.sqs_endpoint_url
    return boto3.client("sqs", **kwargs)


def _publish(
    job_type: str,
    body: dict[str, Any],
    deduplication_id: Optional[str] = None,
) -> None:
    """Publish a single SQS message.  Fire-and-forget.

    * If sqs_enabled is False → immediate no-op.
    * If SQS send fails → logs error, does NOT raise.
    * DB operations are never affected.
    """
    settings = get_settings()
    if not settings.sqs_enabled:
        return

    queue_attr = _QUEUE_URL_ATTRS.get(job_type)
    if queue_attr is None:
        logger.warning("sqs_unknown_job_type", job_type=job_type)
        return

    queue_url = getattr(settings, queue_attr, "")
    if not queue_url:
        logger.warning("sqs_no_queue_url", job_type=job_type)
        return

    try:
        client = _get_sqs_client()
        kwargs: dict[str, Any] = {
            "QueueUrl": queue_url,
            "MessageBody": json.dumps(body, default=str),
            "MessageAttributes": {
                "job_type": {"StringValue": job_type, "DataType": "String"},
                "org_id": {
                    "StringValue": body.get("org_id", ""),
                    "DataType": "String",
                },
                "source": {"StringValue": "api", "DataType": "String"},
            },
        }
        # MessageDeduplicationId is FIFO-queue only.  Standard queues
        # reject it with InvalidParameterValueException.
        if deduplication_id and queue_url.endswith(".fifo"):
            kwargs["MessageDeduplicationId"] = deduplication_id

        resp = client.send_message(**kwargs)
        logger.info(
            "sqs_job_published",
            job_type=job_type,
            message_id=resp.get("MessageId"),
            file_id=body.get("file_id", ""),
        )
    except Exception:
        logger.exception(
            "sqs_publish_failed",
            job_type=job_type,
            file_id=body.get("file_id", ""),
        )


# ── Public API ─────────────────────────────────────────────────────────

def publish_processing_job(
    *,
    file_id: UUID,
    org_id: UUID,
    connection_id: UUID,
    video_id: str,
    google_file_id: str,
    file_name: str,
    mime_type: str,
    file_size_bytes: Optional[int],
    library_id: UUID,
    scope_type: str,
    drive_id: Optional[str],
    google_created_time: Optional[str] = None,
    google_modified_time: Optional[str] = None,
) -> None:
    """Publish a processing-job-created event to the processing queue.

    Called from ``upsert_files`` after new DriveFile rows are flushed.
    """
    now = datetime.now(timezone.utc)
    body = {
        "version": "1",
        "type": "processing.job_created",
        "timestamp": now.isoformat(),
        "file_id": str(file_id),
        "org_id": str(org_id),
        "connection_id": str(connection_id),
        "video_id": video_id,
        "google_file_id": google_file_id,
        "file_name": file_name,
        "mime_type": mime_type,
        "file_size_bytes": file_size_bytes,
        "library_id": str(library_id),
        "scope_type": scope_type,
        "drive_id": drive_id,
        "google_created_time": google_created_time,
        "google_modified_time": google_modified_time,
    }
    dedup_id = f"{file_id}:processing:{now.strftime('%Y%m%dT%H%M')}"
    _publish("processing", body, dedup_id)


def publish_enrichment_jobs(
    *,
    file_id: UUID,
    org_id: UUID,
    video_id: str,
    keyframe_s3_prefix: Optional[str],
    audio_s3_key: Optional[str],
) -> None:
    """Publish per-video (v1) enrichment-job-created events.

    Called from ``update_processing_status`` when status transitions to 'indexed'.

    * OCR + Face published when ``keyframe_s3_prefix`` is set.
    * STT published when ``audio_s3_key`` is set.

    Note: Caption and visual-embed are published as per-scene (v2) messages
    by ``publish_scene_enrichment_jobs()`` instead.
    """
    now = datetime.now(timezone.utc)
    timestamp = now.isoformat()
    minute = now.strftime("%Y%m%dT%H%M")

    if keyframe_s3_prefix:
        for job_type in ("ocr", "face"):
            _publish(
                job_type,
                {
                    "version": "1",
                    "type": "enrichment.job_created",
                    "timestamp": timestamp,
                    "job_type": job_type,
                    "file_id": str(file_id),
                    "org_id": str(org_id),
                    "video_id": video_id,
                    "keyframe_s3_prefix": keyframe_s3_prefix,
                    "audio_s3_key": None,
                },
                f"{file_id}:{job_type}:{minute}",
            )

    if audio_s3_key:
        _publish(
            "stt",
            {
                "version": "1",
                "type": "enrichment.job_created",
                "timestamp": timestamp,
                "job_type": "stt",
                "file_id": str(file_id),
                "org_id": str(org_id),
                "video_id": video_id,
                "keyframe_s3_prefix": None,
                "audio_s3_key": audio_s3_key,
            },
            f"{file_id}:stt:{minute}",
        )


def publish_transcode_job(
    *,
    file_id: UUID,
    org_id: UUID,
    connection_id: UUID,
    video_id: str,
    google_file_id: str,
    file_name: str,
    original_s3_key: str,
    original_size_bytes: int,
    library_id: UUID,
    scope_type: str,
    drive_id: Optional[str],
) -> None:
    """Publish a transcode job to the GPU transcode queue.

    Called from ``update_processing_status`` when status transitions to
    'awaiting_transcode' and drive_transcode_mode='gpu'.
    """
    now = datetime.now(timezone.utc)
    body = {
        "version": "1",
        "type": "transcode.job_created",
        "timestamp": now.isoformat(),
        "file_id": str(file_id),
        "org_id": str(org_id),
        "connection_id": str(connection_id),
        "video_id": video_id,
        "google_file_id": google_file_id,
        "file_name": file_name,
        "original_s3_key": original_s3_key,
        "original_size_bytes": original_size_bytes,
        "library_id": str(library_id),
        "scope_type": scope_type,
        "drive_id": drive_id,
    }
    dedup_id = f"{file_id}:transcode:{now.strftime('%Y%m%dT%H%M')}"
    _publish("transcode", body, dedup_id)


def publish_export_job(
    *,
    export_id: UUID,
    org_id: UUID,
    user_id: UUID,
    export_hash: str,
) -> None:
    """Publish an export job to the export queue.

    Called from the proxy-pack endpoint after creating an ExportRecord.
    The drive-worker consumes this and assembles the ZIP bundle.
    """
    now = datetime.now(timezone.utc)
    body = {
        "version": "1",
        "type": "export.proxy_pack",
        "timestamp": now.isoformat(),
        "export_id": str(export_id),
        "org_id": str(org_id),
        "user_id": str(user_id),
        "export_hash": export_hash,
    }
    dedup_id = f"{export_id}:export:{now.strftime('%Y%m%dT%H%M')}"
    _publish("export", body, dedup_id)


def publish_scene_enrichment_jobs(
    *,
    file_id: UUID,
    org_id: UUID,
    video_id: str,
    scenes: list[dict[str, Any]],
) -> None:
    """Publish per-scene (v2) enrichment jobs for caption and visual-embed.

    Each scene produces one SQS message per job_type, published via
    ``send_message_batch`` (10 msgs/call) for throughput.

    Args:
        scenes: List of dicts with keys: scene_id, scene_index, keyframe_s3_key.

    Called asynchronously from the PATCH status handler after status='indexed'.
    Fire-and-forget — errors are logged but never raised to the caller.
    """
    settings = get_settings()
    if not settings.sqs_enabled:
        return

    if not scenes:
        return

    now = datetime.now(timezone.utc)
    timestamp = now.isoformat()
    client = _get_sqs_client()

    for job_type in ("caption", "visual_embed"):
        queue_attr = _QUEUE_URL_ATTRS.get(job_type)
        if queue_attr is None:
            continue
        queue_url = getattr(settings, queue_attr, "")
        if not queue_url:
            continue

        # Build all message entries for this job_type
        entries: list[dict[str, Any]] = []
        for scene in scenes:
            entries.append({
                "Id": f"{scene['scene_id']}_{job_type}",
                "MessageBody": json.dumps({
                    "version": "2",
                    "type": "enrichment.scene_job_created",
                    "timestamp": timestamp,
                    "job_type": job_type,
                    "file_id": str(file_id),
                    "org_id": str(org_id),
                    "video_id": video_id,
                    "scene_id": scene["scene_id"],
                    "scene_index": scene["scene_index"],
                    "keyframe_s3_key": scene["keyframe_s3_key"],
                    "audio_s3_key": None,
                }, default=str),
                "MessageAttributes": {
                    "job_type": {"StringValue": job_type, "DataType": "String"},
                    "org_id": {"StringValue": str(org_id), "DataType": "String"},
                    "source": {"StringValue": "api", "DataType": "String"},
                    "version": {"StringValue": "2", "DataType": "String"},
                },
            })

        # Send in batches of 10 (SQS maximum per send_message_batch call)
        sqs_batch_size = 10
        published = 0
        failed = 0
        for i in range(0, len(entries), sqs_batch_size):
            batch = entries[i : i + sqs_batch_size]
            try:
                resp = client.send_message_batch(
                    QueueUrl=queue_url, Entries=batch
                )
                published += len(resp.get("Successful", []))
                batch_failed = resp.get("Failed", [])
                if batch_failed:
                    failed += len(batch_failed)
                    logger.warning(
                        "sqs_scene_batch_partial_failure",
                        job_type=job_type,
                        video_id=video_id,
                        batch_start=i,
                        failed_count=len(batch_failed),
                    )
            except Exception:
                failed += len(batch)
                logger.exception(
                    "sqs_scene_batch_send_failed",
                    job_type=job_type,
                    video_id=video_id,
                    batch_start=i,
                )

        logger.info(
            "sqs_scene_jobs_published",
            job_type=job_type,
            video_id=video_id,
            published=published,
            failed=failed,
            total_scenes=len(scenes),
        )