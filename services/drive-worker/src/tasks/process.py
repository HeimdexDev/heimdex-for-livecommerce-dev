"""
Drive file processing via internal HTTP API.

Claims pending files from the API, downloads from Google Drive,
transcodes, detects scenes, uploads artifacts to S3, and ingests
to the search index. No direct database access.
"""
# pyright: reportMissingImports=false

import json
import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, List, Optional
from uuid import UUID

import requests

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build as build_google_service
from googleapiclient.http import MediaIoBaseDownload

from heimdex_worker_sdk import emit_event
from heimdex_worker_sdk.content_type import is_image
from heimdex_worker_sdk.internal_api import InternalAPIClient

logger = logging.getLogger(__name__)
_SERVICE_NAME = "drive-worker"


def _build_drive_web_view_link(google_file_id: str) -> str:
    return f"https://drive.google.com/file/d/{google_file_id}/view"


def _build_drive_service(access_token: str):
    """Build a Google Drive API service from a pre-minted access token."""
    credentials = Credentials(token=access_token)
    return build_google_service("drive", "v3", credentials=credentials)


def process_pending_files(
    api_client: InternalAPIClient,
    settings: Any,
    acquire_slot: Callable[..., bool],
    release_slot: Callable[..., None],
) -> None:
    """Claim and process pending video files.

    Flow per file:
    1. Claim file for processing (lease-based)
    2. Acquire concurrency slot
    3. Get short-lived Google access token via token broker
    4. Download from Google Drive
    5. Transcode to proxy
    6. Detect scenes, extract keyframes
    7. Upload artifacts to S3
    8. Ingest scenes to search index
    9. Report final status (indexed/failed)
    """
    files = api_client.claim_processing(limit=1)
    if not files:
        return

    for claimed_file in files:
        org_id_str = str(claimed_file.org_id)

        if not acquire_slot(org_id_str, settings):
            # Can't process now — release the lease by reporting failure
            try:
                api_client.update_processing_status(
                    claimed_file.id,
                    status="failed",
                    lease_token=claimed_file.lease_token,
                    error="concurrency_slot_unavailable",
                )
            except Exception:
                logger.warning(
                    "process_slot_release_failed",
                    extra={"file_id": str(claimed_file.id)},
                    exc_info=True,
                )
            continue

        try:
            _process_single_file(
                api_client=api_client,
                settings=settings,
                claimed_file=claimed_file,
            )
        except Exception as e:
            logger.exception("process_file_error", extra={"org_id": org_id_str})
        finally:
            release_slot(org_id_str)


def _process_image(
    api_client: InternalAPIClient,
    settings: Any,
    claimed_file: Any,
) -> None:
    from heimdex_worker_sdk.drive_keys import (
        enrichment_keyframe_s3_key,
        enrichment_keyframe_s3_prefix,
        thumbnail_s3_key,
        thumbnail_s3_prefix,
    )
    from heimdex_worker_sdk.s3 import S3Client
    from src.tasks.image_metadata import extract_image_metadata, parse_filename

    org_id_str = str(claimed_file.org_id)
    video_id = claimed_file.video_id
    scene_id = f"{video_id}_scene_000"
    temp_dir = Path(settings.drive_temp_dir) / org_id_str / str(claimed_file.id)
    temp_dir.mkdir(parents=True, exist_ok=True)

    t_start = time.monotonic()

    try:
        token_info = api_client.get_drive_token(
            claimed_file.connection_id,
            lease_token=None,
        )
        service = _build_drive_service(token_info.access_token)

        original_path = temp_dir / f"original_{claimed_file.google_file_id}"
        logger.info("image_download_started", extra={
            "file_id": claimed_file.google_file_id,
            "file_name": claimed_file.file_name,
            "video_id": video_id,
        })

        api_client.update_processing_status(
            claimed_file.id,
            status="downloading",
            lease_token=claimed_file.lease_token,
        )

        budget_bytes = int(settings.drive_temp_disk_budget_gb * 1024 * 1024 * 1024)
        _download_file(
            service=service,
            google_file_id=claimed_file.google_file_id,
            dest_path=original_path,
            budget_bytes=budget_bytes,
        )

        api_client.update_processing_status(
            claimed_file.id,
            status="processing",
            lease_token=claimed_file.lease_token,
        )

        meta = extract_image_metadata(original_path)
        parsed = parse_filename(claimed_file.file_name)
        content_type = claimed_file.mime_type or "application/octet-stream"

        s3 = S3Client(bucket=settings.drive_s3_bucket)
        s3.ensure_bucket()

        thumb_key = thumbnail_s3_key(org_id_str, video_id, scene_id)
        s3.upload_file(original_path, thumb_key, content_type=content_type)

        keyframe_key = enrichment_keyframe_s3_key(org_id_str, video_id, scene_id)
        s3.upload_file(original_path, keyframe_key, content_type=content_type)

        thumb_prefix = thumbnail_s3_prefix(org_id_str, video_id)
        kf_prefix = enrichment_keyframe_s3_prefix(org_id_str, video_id)

        scene = {
            "scene_id": scene_id,
            "index": 0,
            "start_ms": 0,
            "end_ms": 0,
            "keyframe_timestamp_ms": 0,
            "transcript_raw": "",
            "ocr_text_raw": "",
            "source_type": "gdrive",
            "capture_time": claimed_file.google_created_time,
            "web_view_link": claimed_file.web_view_link,
            "content_type": "image",
            "filename_text": " ".join(parsed.tokens),
            "image_width": meta.width,
            "image_height": meta.height,
            "image_orientation": meta.orientation,
        }

        ingest_result = _post_scenes_to_api(
            settings=settings,
            org_id=claimed_file.org_id,
            video_id=video_id,
            video_title=claimed_file.file_name,
            library_id=claimed_file.library_id,
            duration_ms=0,
            scenes=[scene],
            source_path=claimed_file.drive_path,
            web_view_link=(
                claimed_file.web_view_link
                or _build_drive_web_view_link(claimed_file.google_file_id)
            ),
            video_width=meta.width,
            video_height=meta.height,
        )

        if getattr(settings, "drive_enrichment_enabled", False):
            _upload_scene_manifest(
                s3=s3,
                org_id_str=org_id_str,
                video_id=video_id,
                video_title=claimed_file.file_name,
                library_id=claimed_file.library_id,
                duration_ms=0,
                scenes=[scene],
                temp_dir=temp_dir,
            )

        api_client.update_processing_status(
            claimed_file.id,
            status="indexed",
            lease_token=claimed_file.lease_token,
            scene_count=ingest_result.get("indexed_count", 1),
            thumbnail_s3_prefix=thumb_prefix,
            audio_s3_key=None,
            keyframe_s3_prefix=kf_prefix,
            video_width=meta.width,
            video_height=meta.height,
        )

        logger.info(
            "image_process_complete",
            extra={
                "file_id": claimed_file.google_file_id,
                "video_id": video_id,
                "scene_id": scene_id,
                "format": meta.format,
                "width": meta.width,
                "height": meta.height,
                "orientation": meta.orientation,
                "thumbnail_s3_prefix": thumb_prefix,
                "keyframe_s3_prefix": kf_prefix,
            },
        )
        emit_event(
            service=_SERVICE_NAME,
            event_name="drive_completed",
            category="job_success",
            level="INFO",
            org_id=claimed_file.org_id,
            job_id=claimed_file.id,
            duration_ms=int((time.monotonic() - t_start) * 1000),
            metadata={
                "video_id": video_id,
                "mode": "image",
                "format": meta.format,
                "width": meta.width,
                "height": meta.height,
            },
        )
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.error("image_processing_failed", extra={
            "file_id": claimed_file.google_file_id,
            "video_id": video_id,
            "error": error_msg,
        })
        try:
            api_client.update_processing_status(
                claimed_file.id,
                status="failed",
                lease_token=claimed_file.lease_token,
                error=error_msg,
            )
        except Exception:
            logger.warning(
                "image_process_status_update_failed",
                extra={"file_id": str(claimed_file.id)},
                exc_info=True,
            )
        emit_event(
            service=_SERVICE_NAME,
            event_name="drive_failed",
            category="job_failure",
            level="ERROR",
            org_id=claimed_file.org_id,
            job_id=claimed_file.id,
            duration_ms=int((time.monotonic() - t_start) * 1000),
            message=error_msg[:1000],
            metadata={
                "video_id": video_id,
                "mode": "image",
                "error_class": type(e).__name__,
                "error_msg": str(e)[:500],
            },
        )
        raise
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def _process_single_file(
    api_client: InternalAPIClient,
    settings: Any,
    claimed_file: Any,
) -> None:
    mime_type = getattr(claimed_file, "mime_type", "")
    if is_image(mime_type):
        if not getattr(settings, "image_processing_enabled", False):
            logger.info("image_processing_skipped", extra={
                "file_id": str(claimed_file.id),
                "file_name": claimed_file.file_name,
                "reason": "image_processing_disabled",
            })
            emit_event(
                service=_SERVICE_NAME,
                event_name="drive_skipped",
                category="job_failure",
                level="WARNING",
                org_id=claimed_file.org_id,
                job_id=claimed_file.id,
                duration_ms=0,
                message="image_processing_disabled",
                metadata={
                    "video_id": claimed_file.video_id,
                    "mode": "image",
                    "reason": "image_processing_disabled",
                    "error_class": "ImageProcessingDisabled",
                    "mime_type": mime_type,
                },
            )
            return
        return _process_image(api_client, settings, claimed_file)

    from heimdex_worker_sdk.drive_keys import (
        audio_s3_key, enrichment_keyframe_s3_key, enrichment_keyframe_s3_prefix,
        proxy_s3_key, thumbnail_s3_key, thumbnail_s3_prefix,
    )
    from heimdex_media_pipelines.transcoding import make_transcode_decision, probe_video, transcode_to_proxy
    from heimdex_media_pipelines.scenes.detector import detect_scenes
    from heimdex_media_pipelines.scenes.keyframe import extract_all_keyframes
    from heimdex_media_pipelines.scenes.assembler import assemble_scenes
    from heimdex_worker_sdk.s3 import S3Client

    org_id_str = str(claimed_file.org_id)
    temp_dir = Path(settings.drive_temp_dir) / org_id_str / str(claimed_file.id)
    temp_dir.mkdir(parents=True, exist_ok=True)

    t_start = time.monotonic()

    try:
        # Get access token via token broker.
        # Pass lease_token=None because the processing path holds a *file*
        # lease, not a *connection* lease.  The token endpoint allows None.
        token_info = api_client.get_drive_token(
            claimed_file.connection_id,
            lease_token=None,
        )
        service = _build_drive_service(token_info.access_token)

        # Download
        original_path = temp_dir / f"original_{claimed_file.google_file_id}"
        logger.info("download_started", extra={
            "file_id": claimed_file.google_file_id,
            "file_name": claimed_file.file_name,
        })

        api_client.update_processing_status(
            claimed_file.id,
            status="downloading",
            lease_token=claimed_file.lease_token,
        )

        budget_bytes = int(settings.drive_temp_disk_budget_gb * 1024 * 1024 * 1024)
        _download_file(
            service=service,
            google_file_id=claimed_file.google_file_id,
            dest_path=original_path,
            budget_bytes=budget_bytes,
        )

        if settings.drive_transcode_mode == "gpu":
            _handle_gpu_mode(
                api_client=api_client,
                settings=settings,
                claimed_file=claimed_file,
                original_path=original_path,
                temp_dir=temp_dir,
            )
            emit_event(
                service=_SERVICE_NAME,
                event_name="drive_completed",
                category="job_success",
                level="INFO",
                org_id=claimed_file.org_id,
                job_id=claimed_file.id,
                duration_ms=int((time.monotonic() - t_start) * 1000),
                metadata={
                    "video_id": claimed_file.video_id,
                    "mode": "gpu_handoff",
                    "next_stage": "drive_transcode_worker",
                },
            )
            return

        # Transcode
        api_client.update_processing_status(
            claimed_file.id,
            status="transcoding",
            lease_token=claimed_file.lease_token,
        )

        probe = probe_video(original_path)
        max_height = settings.drive_proxy_max_height
        max_bitrate_kbps = int(settings.drive_proxy_max_bitrate.rstrip("k"))
        decision = make_transcode_decision(probe, max_height=max_height, max_bitrate_kbps=max_bitrate_kbps)

        if decision.should_transcode:
            proxy_path = temp_dir / "proxy.mp4"
            transcode_to_proxy(
                original_path, proxy_path, probe, decision,
                max_height=max_height,
                preset=settings.drive_proxy_preset,
                crf=settings.drive_proxy_crf,
                max_bitrate=settings.drive_proxy_max_bitrate,
                bufsize=settings.drive_proxy_bufsize,
                audio_bitrate=settings.drive_proxy_audio_bitrate,
            )
        else:
            proxy_path = original_path
            logger.info("transcode_skipped", extra={
                "reason": decision.reason,
                "file_id": claimed_file.google_file_id,
            })

        # Upload proxy to S3
        s3 = S3Client(bucket=settings.drive_s3_bucket)
        s3.ensure_bucket()
        s3_key = proxy_s3_key(org_id_str, claimed_file.drive_id, claimed_file.google_file_id)
        s3.upload_file(proxy_path, s3_key, content_type="video/mp4")

        proxy_probe = probe_video(proxy_path) if decision.should_transcode else probe
        proxy_size = proxy_path.stat().st_size

        # Two-phase STT-then-split: hand off to STT worker before scene detection
        if getattr(settings, "drive_speech_split_enabled", False):
            _handle_stt_split_handoff(
                api_client=api_client,
                settings=settings,
                claimed_file=claimed_file,
                original_path=original_path,
                s3=s3,
                s3_key=s3_key,
                probe=probe,
                proxy_probe=proxy_probe,
                proxy_size=proxy_size,
                temp_dir=temp_dir,
            )
            emit_event(
                service=_SERVICE_NAME,
                event_name="drive_completed",
                category="job_success",
                level="INFO",
                org_id=claimed_file.org_id,
                job_id=claimed_file.id,
                duration_ms=int((time.monotonic() - t_start) * 1000),
                metadata={
                    "video_id": claimed_file.video_id,
                    "mode": "stt_split_handoff",
                    "next_stage": "drive_stt_worker",
                },
            )
            return

        # Scene detection
        api_client.update_processing_status(
            claimed_file.id,
            status="processing",
            lease_token=claimed_file.lease_token,
        )

        t0 = time.monotonic()
        scene_boundaries = detect_scenes(
            video_path=str(original_path),
            video_id=claimed_file.video_id,
        )
        logger.info(
            "scene_detection_complete",
            extra={
                "video_id": claimed_file.video_id,
                "scene_count": len(scene_boundaries),
                "elapsed_s": round(time.monotonic() - t0, 3),
            },
        )

        keyframe_dir = temp_dir / "keyframes"
        keyframe_paths = extract_all_keyframes(
            video_path=str(original_path),
            scenes=scene_boundaries,
            out_dir=str(keyframe_dir),
        )

        scene_result = assemble_scenes(
            video_path=str(original_path),
            video_id=claimed_file.video_id,
            scene_boundaries=scene_boundaries,
            total_duration_ms=proxy_probe.duration_ms,
        )

        # Upload thumbnails
        for scene_doc in scene_result.scenes:
            if scene_doc.thumbnail_path and Path(scene_doc.thumbnail_path).is_file():
                thumb_key = thumbnail_s3_key(
                    org_id_str, claimed_file.video_id, scene_doc.scene_id,
                )
                s3.upload_file(
                    Path(scene_doc.thumbnail_path), thumb_key,
                    content_type="image/jpeg",
                )

        # Upload enrichment artifacts (audio, keyframes)
        enrichment_fields = _upload_enrichment_artifacts(
            s3=s3,
            original_path=original_path,
            scene_result=scene_result,
            org_id_str=org_id_str,
            video_id=claimed_file.video_id,
            temp_dir=temp_dir,
            enabled=settings.drive_enrichment_enabled,
        )

        # Build scene dicts for ingest
        # Use Google Drive creation time (preferred) or modification time (fallback)
        google_capture_time = claimed_file.google_created_time or claimed_file.google_modified_time
        scene_dicts = _build_ingest_scene_dicts(
            scene_result.scenes,
            source_type="gdrive",
            capture_time=google_capture_time,
            web_view_link=claimed_file.web_view_link,
        )

        if settings.drive_enrichment_enabled:
            _upload_scene_manifest(
                s3=s3,
                org_id_str=org_id_str,
                video_id=claimed_file.video_id,
                video_title=claimed_file.file_name,
                library_id=claimed_file.library_id,
                duration_ms=proxy_probe.duration_ms,
                scenes=scene_dicts,
                temp_dir=temp_dir,
            )

        # Ingest scenes to search index
        ingest_result = _post_scenes_to_api(
            settings=settings,
            org_id=claimed_file.org_id,
            video_id=claimed_file.video_id,
            video_title=claimed_file.file_name,
            library_id=claimed_file.library_id,
            duration_ms=proxy_probe.duration_ms,
            scenes=scene_dicts,
            source_path=claimed_file.drive_path,
            web_view_link=(
                claimed_file.web_view_link
                or _build_drive_web_view_link(claimed_file.google_file_id)
            ),
            video_fps=probe.frame_rate,
            video_width=probe.width,
            video_height=probe.height,
        )

        # Report success
        api_client.update_processing_status(
            claimed_file.id,
            status="indexed",
            lease_token=claimed_file.lease_token,
            scene_count=ingest_result["indexed_count"],
            proxy_s3_key=s3_key,
            proxy_size_bytes=proxy_size,
            proxy_duration_ms=proxy_probe.duration_ms,
            thumbnail_s3_prefix=thumbnail_s3_prefix(org_id_str, claimed_file.video_id),
            audio_s3_key=enrichment_fields.get("audio_s3_key"),
            keyframe_s3_prefix=enrichment_fields.get("keyframe_s3_prefix"),
            # Original video metadata from ffprobe (for FCPXML export).
            # Use the original probe, not proxy_probe, to get true source dimensions.
            video_fps=probe.frame_rate,
            video_width=probe.width,
            video_height=probe.height,
        )

        logger.info(
            "file_processing_complete",
            extra={
                "file_id": claimed_file.google_file_id,
                "video_id": claimed_file.video_id,
                "proxy_s3_key": s3_key,
                "proxy_size_bytes": proxy_size,
                "transcoded": decision.should_transcode,
                "scene_count": len(scene_result.scenes),
                "indexed_count": ingest_result["indexed_count"],
            },
        )

        emit_event(
            service=_SERVICE_NAME,
            event_name="drive_completed",
            category="job_success",
            level="INFO",
            org_id=claimed_file.org_id,
            job_id=claimed_file.id,
            duration_ms=int((time.monotonic() - t_start) * 1000),
            metadata={
                "video_id": claimed_file.video_id,
                "mode": "video_full",
                "transcoded": decision.should_transcode,
                "scene_count": len(scene_result.scenes),
                "indexed_count": ingest_result["indexed_count"],
                "proxy_size_bytes": proxy_size,
            },
        )

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.error("file_processing_failed", extra={
            "file_id": claimed_file.google_file_id,
            "error": error_msg,
        })
        try:
            api_client.update_processing_status(
                claimed_file.id,
                status="failed",
                lease_token=claimed_file.lease_token,
                error=error_msg,
            )
        except Exception:
            logger.warning(
                "process_status_update_failed",
                extra={"file_id": str(claimed_file.id)},
                exc_info=True,
            )
        emit_event(
            service=_SERVICE_NAME,
            event_name="drive_failed",
            category="job_failure",
            level="ERROR",
            org_id=claimed_file.org_id,
            job_id=claimed_file.id,
            duration_ms=int((time.monotonic() - t_start) * 1000),
            message=error_msg[:1000],
            metadata={
                "video_id": claimed_file.video_id,
                "mode": "video_full",
                "error_class": type(e).__name__,
                "error_msg": str(e)[:500],
            },
        )

    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def _handle_gpu_mode(
    api_client: InternalAPIClient,
    settings: Any,
    claimed_file: Any,
    original_path: Path,
    temp_dir: Path,
) -> None:
    """GPU mode: upload original to S3 and hand off to transcode-worker."""
    from heimdex_worker_sdk import drive_keys as drive_keys_module
    from heimdex_worker_sdk.s3 import S3Client

    org_id_str = str(claimed_file.org_id)
    _ = temp_dir

    s3 = S3Client(bucket=settings.drive_s3_bucket)
    s3.ensure_bucket()
    original_key_builder = getattr(drive_keys_module, "original_s3_key", None)
    if callable(original_key_builder):
        s3_key = str(original_key_builder(org_id_str, claimed_file.drive_id, claimed_file.google_file_id))
    else:
        s3_key = f"{org_id_str}/drive/{claimed_file.drive_id}/{claimed_file.google_file_id}/original"
    original_size_bytes = original_path.stat().st_size

    logger.info("gpu_mode_uploading_original", extra={
        "file_id": claimed_file.google_file_id,
        "s3_key": s3_key,
        "size_bytes": original_size_bytes,
    })

    s3.upload_file(
        original_path,
        s3_key,
        content_type=claimed_file.mime_type or "application/octet-stream",
        tags={"lifecycle": "auto-delete"},
    )

    update_processing_status = getattr(api_client, "update_processing_status")
    update_processing_status(
        claimed_file.id,
        status="awaiting_transcode",
        lease_token=claimed_file.lease_token,
        original_s3_key=s3_key,
        original_size_bytes=original_size_bytes,
    )

    logger.info("gpu_mode_handoff_complete", extra={
        "file_id": claimed_file.google_file_id,
        "video_id": claimed_file.video_id,
        "original_s3_key": s3_key,
        "original_size_bytes": original_size_bytes,
    })


def _handle_stt_split_handoff(
    api_client: InternalAPIClient,
    settings: Any,
    claimed_file: Any,
    original_path: Path,
    s3: Any,
    s3_key: str,
    probe: Any,
    proxy_probe: Any,
    proxy_size: int,
    temp_dir: Path,
) -> None:
    """Two-phase pipeline: extract audio, upload to S3, hand off to STT worker."""
    from heimdex_worker_sdk.drive_keys import audio_s3_key as audio_s3_key_fn

    org_id_str = str(claimed_file.org_id)

    # Extract audio from original video
    audio_path = temp_dir / "audio.wav"
    subprocess.run(
        ["ffmpeg", "-i", str(original_path),
         "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
         "-y", str(audio_path)],
        capture_output=True, check=True, timeout=600,
    )
    a_key = audio_s3_key_fn(org_id_str, claimed_file.video_id)
    s3.upload_file(audio_path, a_key, content_type="audio/wav")

    # Report awaiting_stt — triggers API to publish STT job
    api_client.update_processing_status(
        claimed_file.id,
        status="awaiting_stt",
        lease_token=claimed_file.lease_token,
        proxy_s3_key=s3_key,
        proxy_size_bytes=proxy_size,
        proxy_duration_ms=proxy_probe.duration_ms,
        audio_s3_key=a_key,
        video_fps=probe.frame_rate,
        video_width=probe.width,
        video_height=probe.height,
    )

    logger.info("stt_split_phase1_complete", extra={
        "file_id": claimed_file.google_file_id,
        "video_id": claimed_file.video_id,
        "proxy_s3_key": s3_key,
        "audio_s3_key": a_key,
    })


def _download_file(
    service: Any,
    google_file_id: str,
    dest_path: Path,
    budget_bytes: int,
) -> None:
    """Download a file from Google Drive using resumable media download."""
    request = service.files().get_media(fileId=google_file_id, supportsAllDrives=True)
    with open(dest_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if dest_path.stat().st_size > budget_bytes:
                raise RuntimeError(
                    f"Download exceeds disk budget: {dest_path.stat().st_size} > {budget_bytes}"
                )


def _upload_enrichment_artifacts(
    s3: Any,
    original_path: Path,
    scene_result: Any,
    org_id_str: str,
    video_id: str,
    temp_dir: Path,
    enabled: bool = False,
) -> dict[str, str]:
    if not enabled:
        return {}

    from heimdex_worker_sdk.drive_keys import (
        audio_s3_key, enrichment_keyframe_s3_key, enrichment_keyframe_s3_prefix,
    )

    fields: dict[str, str] = {}

    audio_path = temp_dir / "audio.wav"
    t0 = time.monotonic()
    try:
        subprocess.run(
            [
                "ffmpeg", "-i", str(original_path),
                "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                "-y", str(audio_path),
            ],
            capture_output=True,
            check=True,
            timeout=600,
        )
        audio_size = audio_path.stat().st_size
        a_key = audio_s3_key(org_id_str, video_id)
        s3.upload_file(audio_path, a_key, content_type="audio/wav")
        fields["audio_s3_key"] = a_key
        logger.info(
            "enrichment_audio_uploaded",
            extra={
                "video_id": video_id,
                "audio_s3_key": a_key,
                "audio_size_bytes": audio_size,
                "elapsed_s": round(time.monotonic() - t0, 3),
            },
        )
    except Exception:
        logger.warning(
            "enrichment_audio_extract_failed",
            extra={"video_id": video_id},
            exc_info=True,
        )

    kf_prefix = enrichment_keyframe_s3_prefix(org_id_str, video_id)
    kf_count = 0
    for scene_doc in scene_result.scenes:
        if scene_doc.thumbnail_path and Path(scene_doc.thumbnail_path).is_file():
            kf_key = enrichment_keyframe_s3_key(org_id_str, video_id, scene_doc.scene_id)
            try:
                s3.upload_file(
                    Path(scene_doc.thumbnail_path), kf_key,
                    content_type="image/jpeg",
                )
                kf_count += 1
            except Exception:
                logger.warning(
                    "enrichment_keyframe_upload_failed",
                    extra={"video_id": video_id, "scene_id": scene_doc.scene_id},
                    exc_info=True,
                )

    if kf_count > 0:
        fields["keyframe_s3_prefix"] = kf_prefix
        logger.info(
            "enrichment_keyframes_uploaded",
            extra={
                "video_id": video_id,
                "keyframe_s3_prefix": kf_prefix,
                "keyframe_count": kf_count,
            },
        )

    return fields


def _upload_scene_manifest(
    s3: Any,
    org_id_str: str,
    video_id: str,
    video_title: str,
    library_id: UUID,
    duration_ms: int,
    scenes: List[dict[str, Any]],
    temp_dir: Path,
) -> None:
    from heimdex_worker_sdk.drive_keys import scene_manifest_s3_key

    manifest = {
        "video_id": video_id,
        "video_title": video_title,
        "library_id": str(library_id),
        "total_duration_ms": duration_ms,
        "scenes": scenes,
    }
    manifest_path = temp_dir / "scenes.json"
    manifest_path.write_text(json.dumps(manifest))
    key = scene_manifest_s3_key(org_id_str, video_id)
    s3.upload_file(manifest_path, key, content_type="application/json")
    logger.info(
        "scene_manifest_uploaded",
        extra={"video_id": video_id, "s3_key": key, "scene_count": len(scenes)},
    )


def _build_ingest_scene_dicts(
    scene_docs: List[Any],
    source_type: str = "gdrive",
    capture_time: Optional[str] = None,
    web_view_link: Optional[str] = None,
) -> List[dict[str, Any]]:
    result: List[dict[str, Any]] = []
    for doc in scene_docs:
        result.append({
            "scene_id": doc.scene_id,
            "index": doc.index,
            "start_ms": doc.start_ms,
            "end_ms": doc.end_ms,
            "keyframe_timestamp_ms": doc.keyframe_timestamp_ms,
            "transcript_raw": doc.transcript_raw,
            "speech_segment_count": doc.speech_segment_count,
            "keyword_tags": doc.keyword_tags,
            "product_tags": doc.product_tags,
            "product_entities": doc.product_entities,
            "ocr_text_raw": doc.ocr_text_raw,
            "ocr_char_count": doc.ocr_char_count,
            "source_type": source_type,
            "capture_time": capture_time,
            "web_view_link": web_view_link,
            "content_type": "video",
        })
    return result


def _post_scenes_to_api(
    settings: Any,
    org_id: UUID,
    video_id: str,
    video_title: str,
    library_id: UUID,
    duration_ms: int,
    scenes: List[dict[str, Any]],
    source_path: Optional[str] = None,
    web_view_link: Optional[str] = None,
    video_fps: Optional[float] = None,
    video_width: Optional[int] = None,
    video_height: Optional[int] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "video_id": video_id,
        "video_title": video_title,
        "library_id": str(library_id),
        "total_duration_ms": duration_ms,
        "scenes": scenes,
    }
    if source_path is not None:
        payload["source_path"] = source_path
    if web_view_link is not None:
        payload["web_view_link"] = web_view_link
    if video_fps is not None:
        payload["video_fps"] = video_fps
    if video_width is not None:
        payload["video_width"] = video_width
    if video_height is not None:
        payload["video_height"] = video_height
    api_base = settings.drive_api_base_url.rstrip("/")
    url = f"{api_base}/internal/ingest/scenes"

    resp = requests.post(
        url,
        json=payload,
        headers={
            "Authorization": f"Bearer {settings.drive_internal_api_key}",
            "X-Heimdex-Org-Id": str(org_id),
            "Content-Type": "application/json",
        },
        timeout=60,
    )

    if resp.status_code != 200:
        raise RuntimeError(
            f"Internal ingest API returned {resp.status_code}: {resp.text[:500]}"
        )

    return resp.json()
