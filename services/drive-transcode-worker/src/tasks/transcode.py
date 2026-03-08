import json
import importlib
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

import boto3
import requests

logger = logging.getLogger(__name__)


def _update_youtube_status(
    settings: Any,
    file_id: Any,
    org_id: str,
    processing_status: str,
    error: str | None = None,
) -> None:
    """Update YouTube video processing status via the YouTube internal API.

    YouTube videos live in ``youtube_videos`` (not ``drive_files``), so the
    standard ``update_processing_status`` endpoint returns 404. This calls
    the YouTube-specific ``PATCH /internal/youtube/videos/{id}/status``.
    """
    api_base = settings.drive_api_base_url.rstrip("/")
    url = f"{api_base}/internal/youtube/videos/{file_id}/status"
    payload: dict[str, Any] = {"processing_status": processing_status}
    if error:
        payload["enrichment_status"] = {"transcode_error": error[:500]}
    resp = requests.patch(
        url,
        json=payload,
        headers={
            "Authorization": f"Bearer {settings.drive_internal_api_key}",
            "X-Heimdex-Org-Id": org_id,
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"YouTube status update failed ({resp.status_code}): {resp.text[:500]}"
        )


def _process_single_transcode(
    api_client: Any,
    settings: Any,
    claimed_file: Any,
    raw_message: Any | None = None,
) -> None:
    drive_keys = importlib.import_module("heimdex_worker_sdk.drive_keys")
    probe_video = importlib.import_module("heimdex_media_pipelines.transcoding").probe_video
    detect_scenes = importlib.import_module("heimdex_media_pipelines.scenes.detector").detect_scenes
    extract_all_keyframes = importlib.import_module("heimdex_media_pipelines.scenes.keyframe").extract_all_keyframes
    assemble_scenes = importlib.import_module("heimdex_media_pipelines.scenes.assembler").assemble_scenes
    S3Client = importlib.import_module("heimdex_worker_sdk.s3").S3Client

    audio_s3_key = drive_keys.audio_s3_key
    enrichment_keyframe_s3_key = drive_keys.enrichment_keyframe_s3_key
    enrichment_keyframe_s3_prefix = drive_keys.enrichment_keyframe_s3_prefix
    make_original_key = drive_keys.original_s3_key
    proxy_s3_key = drive_keys.proxy_s3_key
    thumbnail_s3_key = drive_keys.thumbnail_s3_key
    thumbnail_s3_prefix = drive_keys.thumbnail_s3_prefix

    org_id = claimed_file.org_id
    org_id_str = str(org_id)
    file_id = claimed_file.id
    lease_token = claimed_file.lease_token

    message_body = getattr(raw_message, "body", {}) if raw_message is not None else {}
    video_id = message_body.get("video_id", claimed_file.video_id)
    google_file_id = message_body.get("google_file_id")
    drive_id = message_body.get("drive_id") or "None"  # folder-scoped connections have no drive_id
    file_name = message_body.get("file_name", video_id)
    library_id = message_body.get("library_id")
    source_path = message_body.get("source_path")
    source_type = message_body.get("source_type", "gdrive")

    if not google_file_id:
        raise RuntimeError("missing_google_file_id_in_transcode_message")

    original_key = message_body.get("original_s3_key")
    if not original_key:
        original_key = make_original_key(org_id_str, drive_id, google_file_id)

    temp_dir = Path(settings.drive_temp_dir) / org_id_str / str(file_id)
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        s3 = S3Client(bucket=settings.drive_s3_bucket)
        s3.ensure_bucket()

        original_path = temp_dir / f"original_{google_file_id}"
        s3.download_file(original_key, original_path)

        # Probe original video BEFORE transcoding to capture true source metadata
        # (fps, width, height). Transcoding changes resolution; fps is preserved.
        original_probe = probe_video(original_path)

        if source_type == "youtube":
            _update_youtube_status(settings, file_id, org_id_str, "transcoding")
        else:
            api_client.update_processing_status(
                file_id,
                status="transcoding",
                lease_token=lease_token,
            )

        proxy_path = temp_dir / "proxy.mp4"

        # Try NVENC (GPU) first, fall back to libx264 (CPU) if unavailable.
        nvenc_cmd = [
            "ffmpeg", "-y",
            "-hwaccel", "cuda",
            "-hwaccel_output_format", "cuda",
            "-i", str(original_path),
            "-c:v", "h264_nvenc",
            "-preset", "p4",
            "-rc", "vbr",
            "-cq", str(settings.drive_proxy_crf),
            "-maxrate", settings.drive_proxy_max_bitrate,
            "-bufsize", settings.drive_proxy_bufsize,
            "-vf", f"scale_cuda=-2:{settings.drive_proxy_max_height}",
            "-c:a", "aac",
            "-b:a", settings.drive_proxy_audio_bitrate,
            "-movflags", "+faststart",
            str(proxy_path),
        ]
        result = subprocess.run(nvenc_cmd, capture_output=True, timeout=7200)
        if result.returncode != 0:
            nvenc_err = result.stderr.decode(errors="ignore")[-300:]
            logger.warning(
                "ffmpeg_nvenc_failed_trying_cpu",
                extra={"error": nvenc_err, "video_id": video_id},
            )
            # CPU fallback: libx264 with scale filter (no CUDA)
            cpu_cmd = [
                "ffmpeg", "-y",
                "-i", str(original_path),
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", str(settings.drive_proxy_crf),
                "-maxrate", settings.drive_proxy_max_bitrate,
                "-bufsize", settings.drive_proxy_bufsize,
                "-vf", f"scale=-2:{settings.drive_proxy_max_height}",
                "-c:a", "aac",
                "-b:a", settings.drive_proxy_audio_bitrate,
                "-movflags", "+faststart",
                str(proxy_path),
            ]
            cpu_result = subprocess.run(cpu_cmd, capture_output=True, timeout=7200)
            if cpu_result.returncode != 0:
                raise RuntimeError(
                    f"ffmpeg failed (NVENC + CPU): {cpu_result.stderr.decode(errors='ignore')[-500:]}"
                )

        proxy_key = proxy_s3_key(org_id_str, drive_id, google_file_id)
        s3.upload_file(proxy_path, proxy_key, content_type="video/mp4")

        if source_type != "youtube":
            api_client.update_processing_status(
                file_id,
                status="processing",
                lease_token=lease_token,
            )

        proxy_probe = probe_video(proxy_path)
        scene_boundaries = detect_scenes(video_path=str(proxy_path), video_id=video_id)
        extract_all_keyframes(
            video_path=str(proxy_path),
            scenes=scene_boundaries,
            out_dir=str(temp_dir / "keyframes"),
        )
        scene_result = assemble_scenes(
            video_path=str(proxy_path),
            video_id=video_id,
            scene_boundaries=scene_boundaries,
            total_duration_ms=proxy_probe.duration_ms,
        )

        for scene_doc in scene_result.scenes:
            if scene_doc.thumbnail_path and Path(scene_doc.thumbnail_path).is_file():
                thumb_key = thumbnail_s3_key(org_id_str, video_id, scene_doc.scene_id)
                s3.upload_file(Path(scene_doc.thumbnail_path), thumb_key, content_type="image/jpeg")

                kf_key = enrichment_keyframe_s3_key(org_id_str, video_id, scene_doc.scene_id)
                s3.upload_file(Path(scene_doc.thumbnail_path), kf_key, content_type="image/jpeg")

        audio_path = temp_dir / "audio.wav"
        _ = subprocess.run(
            [
                "ffmpeg",
                "-i",
                str(proxy_path),
                "-vn",
                "-acodec",
                "pcm_s16le",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-y",
                str(audio_path),
            ],
            capture_output=True,
            check=True,
            timeout=600,
        )
        audio_key = audio_s3_key(org_id_str, video_id)
        s3.upload_file(audio_path, audio_key, content_type="audio/wav")

        scene_dicts = _build_ingest_scene_dicts(scene_result.scenes, source_type=source_type, capture_time=None)
        _upload_scene_manifest(
            s3=s3,
            org_id_str=org_id_str,
            video_id=video_id,
            video_title=file_name,
            library_id=library_id,
            duration_ms=proxy_probe.duration_ms,
            scenes=scene_dicts,
            temp_dir=temp_dir,
        )

        INGEST_BATCH_SIZE = 200
        total_indexed = 0
        for batch_start in range(0, len(scene_dicts), INGEST_BATCH_SIZE):
            batch = scene_dicts[batch_start : batch_start + INGEST_BATCH_SIZE]
            ingest_result = _post_scenes_to_api(
                settings=settings,
                org_id=org_id,
                video_id=video_id,
                video_title=file_name,
                library_id=library_id,
                duration_ms=proxy_probe.duration_ms,
                scenes=batch,
                source_path=source_path,
                video_fps=original_probe.frame_rate,
                video_width=original_probe.width,
                video_height=original_probe.height,
            )
            total_indexed += ingest_result.get("indexed_count", 0)
            logger.info(
                "ingest_batch_complete",
                extra={
                    "batch_start": batch_start,
                    "batch_size": len(batch),
                    "total_scenes": len(scene_dicts),
                    "batch_indexed": ingest_result.get("indexed_count", 0),
                },
            )
        logger.info("transcode_ingest_complete", extra={"indexed_count": total_indexed, "total_scenes": len(scene_dicts)})

        if source_type == "youtube":
            _update_youtube_status(settings, file_id, org_id_str, "indexed")
        else:
            api_client.update_processing_status(
                file_id,
                status="indexed",
                lease_token=lease_token,
                scene_count=len(scene_result.scenes),
                proxy_s3_key=proxy_key,
                proxy_size_bytes=proxy_path.stat().st_size,
                proxy_duration_ms=proxy_probe.duration_ms,
                thumbnail_s3_prefix=thumbnail_s3_prefix(org_id_str, video_id),
                audio_s3_key=audio_key,
                keyframe_s3_prefix=enrichment_keyframe_s3_prefix(org_id_str, video_id),
                video_fps=original_probe.frame_rate,
                video_width=original_probe.width,
                video_height=original_probe.height,
            )

        try:
            s3_client = boto3.client("s3", region_name=settings.s3_region)
            s3_client.delete_object(Bucket=settings.drive_s3_bucket, Key=original_key)
            logger.info("original_deleted_from_s3", extra={"key": original_key})
        except Exception:
            logger.warning("original_delete_failed", extra={"key": original_key}, exc_info=True)

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        try:
            if source_type == "youtube":
                _update_youtube_status(settings, file_id, org_id_str, "failed", error=error_msg)
            else:
                api_client.update_processing_status(
                    file_id,
                    status="failed",
                    lease_token=lease_token,
                    error=error_msg,
                )
        except Exception:
            logger.warning(
                "transcode_status_update_failed",
                extra={"file_id": str(file_id)},
                exc_info=True,
            )
        logger.exception(
            "transcode_processing_failed",
            extra={"org_id": org_id_str, "video_id": video_id, "file_id": str(file_id)},
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _upload_scene_manifest(
    s3: Any,
    org_id_str: str,
    video_id: str,
    video_title: str,
    library_id: str | None,
    duration_ms: int,
    scenes: list[dict[str, Any]],
    temp_dir: Path,
) -> None:
    from heimdex_worker_sdk.drive_keys import scene_manifest_s3_key

    manifest = {
        "video_id": video_id,
        "video_title": video_title,
        "library_id": str(library_id) if library_id else None,
        "total_duration_ms": duration_ms,
        "scenes": scenes,
    }
    manifest_path = temp_dir / "scenes.json"
    _ = manifest_path.write_text(json.dumps(manifest))
    key = scene_manifest_s3_key(org_id_str, video_id)
    s3.upload_file(manifest_path, key, content_type="application/json")
    logger.info(
        "scene_manifest_uploaded",
        extra={"video_id": video_id, "s3_key": key, "scene_count": len(scenes)},
    )


def _build_ingest_scene_dicts(
    scene_docs: list[Any],
    source_type: str = "gdrive",
    capture_time: str | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for doc in scene_docs:
        result.append(
            {
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
                "content_type": "video",
            }
        )
    return result


def _post_scenes_to_api(
    settings: Any,
    org_id: Any,
    video_id: str,
    video_title: str,
    library_id: str | None,
    duration_ms: int,
    scenes: list[dict[str, Any]],
    source_path: str | None = None,
    video_fps: float | None = None,
    video_width: int | None = None,
    video_height: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "video_id": video_id,
        "video_title": video_title,
        "library_id": str(library_id) if library_id else None,
        "total_duration_ms": duration_ms,
        "scenes": scenes,
    }
    if source_path is not None:
        payload["source_path"] = source_path
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
        raise RuntimeError(f"Internal ingest API returned {resp.status_code}: {resp.text[:500]}")

    return resp.json()
