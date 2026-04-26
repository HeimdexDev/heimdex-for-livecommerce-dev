"""
Queue producer for job creation events (SQS or RabbitMQ).

Publishes messages alongside DB writes when sqs_enabled=true (SQS) or
queue_backend=rabbitmq. All sends are fire-and-forget with structured
error logging. DB operations are NEVER affected by queue failures.

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


_gpu_settings_configured = False
_gpu_import_failed_logged = False


def _wake_gpu_worker(job_type: str) -> None:
    """Wake the Aircloud GPU worker for this job type.  Fire-and-forget.

    History: prior to 2026-04-14 ``heimdex-worker-sdk`` was not listed in
    ``services/api/pyproject.toml`` and every call below hit a silent
    ``ModuleNotFoundError`` caught by a bare ``except Exception``. That
    meant the api-side fast-wake path was effectively disabled for all
    GPU workers, and the only wake mechanism was drive-worker's
    APScheduler ``check_and_manage`` cron (5-minute interval). The fix:
    added the dependency to pyproject.toml, rebuilt the api image, and
    tightened the error handling below so a regression can't silently
    recur — an ``ImportError`` now logs exactly once and other
    exceptions log at WARNING level so ops has visibility into
    orchestrator failures.

    Error handling contract (must stay fire-and-forget):

      * ImportError → log once (module_unavailable), no-op afterward.
        This is a deploy-time bug that should NEVER happen in
        production but we don't want to blow up the HTTP request if
        it does.
      * Any other exception → log at WARNING and swallow. Real
        Aircloud / network failures must not fail the user's
        ``POST /api/<x>/...`` call — the SQS message was already
        sent successfully before this function ran; a failed wake
        just means up-to-5-min latency until the drive-worker cron
        compensates.
    """
    global _gpu_settings_configured, _gpu_import_failed_logged
    try:
        if not _gpu_settings_configured:
            from heimdex_worker_sdk.gpu_orchestrator import configure_settings_provider
            configure_settings_provider(get_settings)
            _gpu_settings_configured = True
        from heimdex_worker_sdk.gpu_orchestrator import ensure_worker_running
        ensure_worker_running(job_type)
    except ImportError:
        if not _gpu_import_failed_logged:
            logger.error(
                "gpu_orchestrator_module_unavailable",
                job_type=job_type,
                hint=(
                    "heimdex-worker-sdk is missing from the api image — "
                    "add it to services/api/pyproject.toml dependencies "
                    "and rebuild"
                ),
            )
            _gpu_import_failed_logged = True
    except Exception:
        # ``logger.exception`` matches the existing pattern in
        # ``_publish`` (structlog-wrapped stdlib; captures exc_info
        # automatically via the current traceback).
        logger.exception(
            "gpu_orchestrator_wake_failed",
            job_type=job_type,
        )


# ── Queue URL mapping ──────────────────────────────────────────────────

_QUEUE_URL_ATTRS = {
    "processing": "sqs_processing_queue_url",
    "resplit": "sqs_processing_queue_url",
    "caption": "sqs_caption_queue_url",
    "stt": "sqs_stt_queue_url",
    "ocr": "sqs_ocr_queue_url",
    "transcode": "sqs_transcode_queue_url",
    "face": "sqs_face_queue_url",
    "visual_embed": "sqs_visual_embed_queue_url",
    "color_extract": "sqs_visual_embed_queue_url",
    "export": "sqs_export_queue_url",
    "shorts_render": "sqs_shorts_render_queue_url",
    "blur": "sqs_blur_queue_url",
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
    """Publish a single queue message.  Fire-and-forget.

    Routes to SQS or RabbitMQ based on ``queue_backend`` setting.

    * If neither sqs_enabled nor queue_backend=rabbitmq → immediate no-op.
    * If queue send fails → logs error, does NOT raise.
    * DB operations are never affected.
    """
    settings = get_settings()

    if settings.queue_backend == "rabbitmq":
        _publish_rabbitmq(job_type, body, deduplication_id)
        return

    # Default: SQS
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
        if deduplication_id and queue_url.endswith(".fifo"):
            kwargs["MessageDeduplicationId"] = deduplication_id

        resp = client.send_message(**kwargs)
        logger.info(
            "queue_job_published",
            backend="sqs",
            job_type=job_type,
            message_id=resp.get("MessageId"),
            file_id=body.get("file_id", ""),
        )
        _wake_gpu_worker(job_type)
    except Exception:
        logger.exception(
            "queue_publish_failed",
            backend="sqs",
            job_type=job_type,
            file_id=body.get("file_id", ""),
        )


# ── RabbitMQ publisher ────────────────────────────────────────────────

_rabbitmq_client = None


def _get_rabbitmq_client():
    """Lazily create and cache RabbitMQ connection."""
    global _rabbitmq_client
    if _rabbitmq_client is not None:
        return _rabbitmq_client

    import pika

    settings = get_settings()
    credentials = pika.PlainCredentials(
        settings.rabbitmq_username, settings.rabbitmq_password
    )
    params = pika.ConnectionParameters(
        host=settings.rabbitmq_host,
        port=settings.rabbitmq_port,
        virtual_host=settings.rabbitmq_vhost,
        credentials=credentials,
        heartbeat=600,
        blocked_connection_timeout=300,
    )
    conn = pika.BlockingConnection(params)
    _rabbitmq_client = conn.channel()
    return _rabbitmq_client


def _publish_rabbitmq(
    job_type: str,
    body: dict[str, Any],
    deduplication_id: Optional[str] = None,
) -> None:
    """Publish to RabbitMQ.  Fire-and-forget."""
    # Map job_type to queue name using the same logical names
    queue_attr = _QUEUE_URL_ATTRS.get(job_type)
    if queue_attr is None:
        logger.warning("queue_unknown_job_type", job_type=job_type)
        return

    settings = get_settings()
    # Derive queue name: "heimdex.caption", "heimdex.processing", etc.
    logical_name = queue_attr.replace("sqs_", "").replace("_queue_url", "")
    queue_name = f"{settings.rabbitmq_queue_prefix}.{logical_name}"

    try:
        import pika

        channel = _get_rabbitmq_client()
        channel.queue_declare(queue=queue_name, durable=True)
        channel.basic_publish(
            exchange="",
            routing_key=queue_name,
            body=json.dumps(body, default=str),
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json",
                message_id=deduplication_id or "",
            ),
        )
        logger.info(
            "queue_job_published",
            backend="rabbitmq",
            job_type=job_type,
            queue=queue_name,
            file_id=body.get("file_id", ""),
        )
        _wake_gpu_worker(job_type)
    except Exception:
        # Reset client on failure so next call reconnects
        global _rabbitmq_client
        _rabbitmq_client = None
        logger.exception(
            "queue_publish_failed",
            backend="rabbitmq",
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
    stt_already_done: bool = False,
) -> None:
    """Publish per-video (v1) enrichment-job-created events.

    Called from ``update_processing_status`` when status transitions to 'indexed'.

    * OCR + Face published when ``keyframe_s3_prefix`` is set.
    * STT published when ``audio_s3_key`` is set and ``stt_already_done`` is False.

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

    if audio_s3_key and not stt_already_done:
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


def publish_stt_for_splitting(
    *,
    file_id: UUID,
    org_id: UUID,
    video_id: str,
    audio_s3_key: str,
) -> None:
    """Publish STT job with callback_mode='scene_split'.

    STT worker will upload result to S3 and call back the API to
    trigger speech-aware scene detection.
    """
    now = datetime.now(timezone.utc)
    body = {
        "version": "1",
        "type": "enrichment.job_created",
        "timestamp": now.isoformat(),
        "job_type": "stt",
        "file_id": str(file_id),
        "org_id": str(org_id),
        "video_id": video_id,
        "keyframe_s3_prefix": None,
        "audio_s3_key": audio_s3_key,
        "callback_mode": "scene_split",
    }
    _publish("stt", body, f"{file_id}:stt_split:{now.strftime('%Y%m%dT%H%M')}")


def publish_scene_split_job(
    *,
    file_id: UUID,
    org_id: UUID,
    video_id: str,
    proxy_s3_key: str,
    stt_result_s3_key: Optional[str],
    audio_s3_key: Optional[str],
    connection_id: str,
    library_id: str,
    file_name: str,
    google_created_time: Optional[str],
    google_modified_time: Optional[str],
) -> None:
    """Publish scene_split job to the processing queue.

    drive-worker will run split_scenes() with speech data.
    """
    now = datetime.now(timezone.utc)
    body = {
        "version": "1",
        "type": "scene_split.job_created",
        "timestamp": now.isoformat(),
        "file_id": str(file_id),
        "org_id": str(org_id),
        "video_id": video_id,
        "proxy_s3_key": proxy_s3_key,
        "stt_result_s3_key": stt_result_s3_key,
        "stt_available": stt_result_s3_key is not None,
        "audio_s3_key": audio_s3_key,
        "connection_id": connection_id,
        "library_id": library_id,
        "file_name": file_name,
        "google_created_time": google_created_time,
        "google_modified_time": google_modified_time,
    }
    _publish("processing", body, f"{file_id}:scene_split:{now.strftime('%Y%m%dT%H%M')}")


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


def publish_youtube_transcode_job(
    *,
    file_id: UUID,
    org_id: UUID,
    video_id: str,
    youtube_video_id: str,
    file_name: str,
    original_s3_key: str,
    original_size_bytes: int,
    library_id: UUID,
    source_type: str = "youtube",
    web_view_link: str | None = None,
) -> None:
    """Publish a YouTube transcode job to the shared GPU transcode queue.

    Called from the YouTube internal router after the worker uploads the
    original video to S3.  Uses ``source_type='youtube'`` so the transcode
    worker tags ingested scenes correctly.
    """
    now = datetime.now(timezone.utc)
    body = {
        "version": "1",
        "type": "transcode.job_created",
        "timestamp": now.isoformat(),
        "file_id": str(file_id),
        "org_id": str(org_id),
        "video_id": video_id,
        "google_file_id": youtube_video_id,
        "file_name": file_name,
        "original_s3_key": original_s3_key,
        "original_size_bytes": original_size_bytes,
        "library_id": str(library_id),
        "scope_type": "youtube",
        "drive_id": "youtube",
        "source_type": source_type,
        "web_view_link": web_view_link,
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


def publish_resplit_job(
    *,
    job_id: UUID,
    org_id: UUID,
    video_id: str,
    source_type: str,
    proxy_s3_key: str,
    keyframe_s3_prefix: str,
    audio_s3_key: str,
    library_id: str,
    video_title: str,
    scene_params: dict[str, Any],
) -> None:
    now = datetime.now(timezone.utc)
    body = {
        "version": "1",
        "type": "resplit.job_created",
        "timestamp": now.isoformat(),
        "job_id": str(job_id),
        "org_id": str(org_id),
        "video_id": video_id,
        "source_type": source_type,
        "proxy_s3_key": proxy_s3_key,
        "keyframe_s3_prefix": keyframe_s3_prefix,
        "audio_s3_key": audio_s3_key or "",
        "library_id": library_id,
        "video_title": video_title,
        "scene_params": scene_params,
    }
    dedup_id = f"{job_id}:resplit:{now.strftime('%Y%m%dT%H%M')}"
    _publish("resplit", body, dedup_id)


def publish_scene_enrichment_jobs(
    *,
    file_id: UUID,
    org_id: UUID,
    video_id: str,
    scenes: list[dict[str, Any]],
    job_types: tuple[str, ...] = ("caption", "visual_embed"),
) -> None:
    """Publish per-scene (v2) enrichment jobs for caption and/or visual-embed.

    Each scene produces one SQS message per job_type, published via
    ``send_message_batch`` (10 msgs/call) for throughput.

    Args:
        scenes: List of dicts with keys: scene_id, scene_index, keyframe_s3_key.
            For caption jobs, optional keys: transcript_raw (str).
        job_types: Which job types to publish. Default is both caption and
            visual_embed. Pass ``("visual_embed",)`` to defer caption.

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

    for job_type in job_types:
        queue_attr = _QUEUE_URL_ATTRS.get(job_type)
        if queue_attr is None:
            continue
        queue_url = getattr(settings, queue_attr, "")
        if not queue_url:
            continue

        # Build all message entries for this job_type
        entries: list[dict[str, Any]] = []
        for scene in scenes:
            msg_body: dict[str, Any] = {
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
            }
            # Include transcript and VLM flag for caption jobs
            if job_type == "caption":
                transcript = scene.get("transcript_raw")
                if transcript:
                    msg_body["transcript_raw"] = transcript
                msg_body["vlm_tags_enabled"] = settings.vlm_tags_enabled
                msg_body["ai_tags_enabled"] = settings.ai_tags_enabled

            entries.append({
                "Id": f"{scene['scene_id']}_{job_type}",
                "MessageBody": json.dumps(msg_body, default=str),
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
        if published > 0:
            _wake_gpu_worker(job_type)


def publish_blur_job(
    *,
    job_id: UUID,
    file_id: UUID,
    org_id: UUID,
    video_id: str,
    proxy_s3_key: str,
    options: dict[str, Any],
) -> None:
    """Publish a user-triggered blur job to the blur queue.

    Called from ``BlurService.create_blur_job`` AFTER the ``blur_jobs``
    row is flushed. Fire-and-forget semantics match the rest of this
    module; the caller is responsible for marking the row ``failed``
    if publish blows up so the user sees the error instead of a
    permanently stuck ``queued`` row.
    """
    settings = get_settings()
    if not settings.sqs_enabled:
        return

    now = datetime.now(timezone.utc)
    body = {
        "version": "1",
        "type": "blur.job_created",
        "timestamp": now.isoformat(),
        "job_id": str(job_id),
        "file_id": str(file_id),
        "org_id": str(org_id),
        "video_id": video_id,
        "source_s3_key": proxy_s3_key,
        "source_kind": "proxy",
        "options": options,
    }
    dedup_id = f"{job_id}:blur:{now.strftime('%Y%m%dT%H%M')}"
    _publish("blur", body, dedup_id)


def publish_blur_export(
    *,
    export_id: UUID,
    blur_job_id: UUID,
    file_id: UUID,
    org_id: UUID,
    video_id: str,
    source_s3_key: str,
    mask_s3_keys: dict[str, str],
    categories: list[str],
    export_format: str,
) -> None:
    """Publish a user-triggered blur layer export to the blur queue.

    Called from ``BlurExportService.create_export`` after the
    ``blur_exports`` row is flushed. Rides the same
    ``heimdex-blur-queue`` as ``blur.job_created``; the worker's
    dispatcher routes by ``type`` so no new SQS infrastructure is
    required. Fire-and-forget, failure fallback lives in the caller.
    """
    settings = get_settings()
    if not settings.sqs_enabled:
        return

    now = datetime.now(timezone.utc)
    body = {
        "version": "1",
        "type": "blur.export_created",
        "timestamp": now.isoformat(),
        "export_id": str(export_id),
        "blur_job_id": str(blur_job_id),
        "file_id": str(file_id),
        "org_id": str(org_id),
        "video_id": video_id,
        "source_s3_key": source_s3_key,
        "mask_s3_keys": mask_s3_keys,
        "options": {
            "categories": list(categories),
            "format": export_format,
        },
    }
    dedup_id = f"{export_id}:blur-export:{now.strftime('%Y%m%dT%H%M')}"
    _publish("blur", body, dedup_id)


def publish_shorts_render_job(
    *,
    job_id: UUID,
    org_id: UUID,
    video_id: str,
    input_spec: dict[str, Any],
) -> None:
    """Publish a shorts render job to the render queue.

    Called from ShortsRenderService after creating a render job record.
    Unlike other producers, this RAISES on failure so the service can
    mark the job as failed instead of leaving it stuck in "queued".
    """
    settings = get_settings()
    if not settings.sqs_enabled:
        raise RuntimeError("SQS is not enabled — cannot enqueue render job")

    queue_url = settings.sqs_shorts_render_queue_url
    if not queue_url:
        raise RuntimeError("SQS_SHORTS_RENDER_QUEUE_URL is not configured")

    now = datetime.now(timezone.utc)
    body = {
        "version": "1",
        "type": "shorts_render.job_created",
        "timestamp": now.isoformat(),
        "job_id": str(job_id),
        "org_id": str(org_id),
        "video_id": video_id,
        "input_spec": input_spec,
    }

    client = _get_sqs_client()
    resp = client.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(body, default=str),
        MessageAttributes={
            "job_type": {"StringValue": "shorts_render", "DataType": "String"},
            "org_id": {"StringValue": str(org_id), "DataType": "String"},
            "source": {"StringValue": "api", "DataType": "String"},
        },
    )
    logger.info(
        "sqs_job_published",
        job_type="shorts_render",
        message_id=resp.get("MessageId"),
        job_id=str(job_id),
    )
