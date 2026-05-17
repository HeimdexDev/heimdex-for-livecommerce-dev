import importlib
import json
import logging
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from heimdex_worker_sdk import emit_event

logger = logging.getLogger(__name__)
_SERVICE_NAME = "drive-caption-worker"


def _safe_update_job_status(api_client: Any, video_id: str, file_id: Any, **kwargs: Any) -> None:
    if video_id.startswith("yt_"):
        return
    api_client.update_job_status(file_id, **kwargs)


async def process_caption_pending_files(api_client: Any, settings: Any, caption_engine: Any = None) -> None:
    files = api_client.claim_jobs("caption", limit=1)

    for claimed_file in files:
        _process_single_caption(
            api_client=api_client,
            settings=settings,
            claimed_file=claimed_file,
            caption_engine=caption_engine,
        )


def _process_single_caption(
    api_client: Any,
    settings: Any,
    claimed_file: Any,
    caption_engine: Any = None,
) -> None:
    drive_keys = importlib.import_module("heimdex_worker_sdk.drive_keys")
    scene_manifest_s3_key = drive_keys.scene_manifest_s3_key
    enrichment_keyframe_s3_key = drive_keys.enrichment_keyframe_s3_key
    S3Client = importlib.import_module("heimdex_worker_sdk.s3").S3Client

    org_id = claimed_file.org_id
    org_id_str = str(org_id)
    file_id = claimed_file.id
    lease_token = claimed_file.lease_token
    video_id = claimed_file.video_id
    temp_dir = Path(tempfile.mkdtemp(prefix=f"caption_{video_id}_"))

    t_start = time.monotonic()

    try:
        s3 = S3Client(bucket=settings.drive_s3_bucket)
        manifest_key = scene_manifest_s3_key(org_id_str, video_id)
        manifest_path = temp_dir / "scenes.json"

        try:
            s3.download_file(manifest_key, manifest_path)
        except Exception as e:
            error_msg = f"manifest_download_failed: {type(e).__name__}: {e}"
            _safe_update_job_status(api_client, video_id, file_id, job_type="caption", status="failed", error=error_msg, lease_token=lease_token)
            emit_event(
                service=_SERVICE_NAME,
                event_name="caption_failed",
                category="job_failure",
                level="ERROR",
                org_id=org_id,
                job_id=file_id,
                duration_ms=int((time.monotonic() - t_start) * 1000),
                message=error_msg[:1000],
                metadata={
                    "video_id": video_id,
                    "stage": "manifest_download",
                    "error_class": type(e).__name__,
                    "error_msg": str(e)[:500],
                },
            )
            return

        manifest = json.loads(manifest_path.read_text())
        scenes = manifest.get("scenes", [])
        scene_count = len(scenes)

        if scene_count == 0:
            _safe_update_job_status(api_client, video_id, file_id, job_type="caption", status="done", lease_token=lease_token)
            emit_event(
                service=_SERVICE_NAME,
                event_name="caption_skipped",
                category="job_failure",
                level="WARNING",
                org_id=org_id,
                job_id=file_id,
                duration_ms=int((time.monotonic() - t_start) * 1000),
                message="no_scenes_in_manifest",
                metadata={
                    "video_id": video_id,
                    "reason": "no_scenes",
                    "error_class": "NoScenes",
                },
            )
            return

        keyframes_dir = temp_dir / "keyframes"
        keyframes_dir.mkdir(parents=True, exist_ok=True)

        download_tasks: list[tuple[int, str, str, Path]] = []
        for scene_idx, scene in enumerate(scenes):
            scene_id = scene.get("scene_id")
            if not scene_id:
                continue
            s3_key = enrichment_keyframe_s3_key(org_id_str, video_id, scene_id)
            local_path = keyframes_dir / f"{scene_id}.jpg"
            download_tasks.append((scene_idx, scene_id, s3_key, local_path))

        caption_started = time.monotonic()
        if caption_engine is None:
            _create = importlib.import_module("heimdex_media_pipelines.vision").create_caption_engine
            caption_engine = _create(model=getattr(settings, "caption_engine", "qwen2vl"), use_gpu=settings.use_gpu)
        engine = caption_engine

        downloaded_keyframes: dict[int, Path] = {}
        caption_results: dict[int, str] = {}
        download_failures = 0
        n_workers = min(8, max(1, len(download_tasks)))

        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            future_to_task = {
                pool.submit(s3.download_file, s3_key, local_path): (scene_idx, scene_id, local_path)
                for scene_idx, scene_id, s3_key, local_path in download_tasks
            }
            for future in as_completed(future_to_task):
                scene_idx, scene_id, local_path = future_to_task[future]
                try:
                    future.result()
                    downloaded_keyframes[scene_idx] = local_path
                    result = engine.caption(str(local_path))
                    if result.caption:
                        caption_results[scene_idx] = result.caption
                except Exception:
                    download_failures += 1
                    logger.warning(
                        "caption_keyframe_download_failed",
                        extra={"org_id": org_id_str, "video_id": video_id, "scene_id": scene_id},
                    )

        if not downloaded_keyframes:
            _safe_update_job_status(
                api_client, video_id, file_id, job_type="caption", status="failed", error="no_keyframes_downloaded", lease_token=lease_token,
            )
            emit_event(
                service=_SERVICE_NAME,
                event_name="caption_failed",
                category="job_failure",
                level="ERROR",
                org_id=org_id,
                job_id=file_id,
                duration_ms=int((time.monotonic() - t_start) * 1000),
                message="no_keyframes_downloaded",
                metadata={
                    "video_id": video_id,
                    "stage": "keyframe_download",
                    "error_class": "NoKeyframesDownloaded",
                    "scene_count": scene_count,
                    "download_failures": download_failures,
                },
            )
            return

        updated_scenes: list[dict[str, Any]] = []
        total_caption_chars = 0
        frames_with_caption = 0
        for i, scene in enumerate(scenes):
            scene_copy = dict(scene)
            if i in caption_results:
                caption_text = caption_results[i][:5_000]
                scene_copy["scene_caption"] = caption_text
                total_caption_chars += len(caption_text)
                frames_with_caption += 1
            updated_scenes.append(scene_copy)

        try:
            ingest_result = _post_enrich_to_api(
                settings=settings,
                org_id=org_id,
                video_id=video_id,
                scenes=updated_scenes,
            )
        except Exception as e:
            error_msg = f"caption_reingest_failed: {type(e).__name__}: {e}"
            _safe_update_job_status(api_client, video_id, file_id, job_type="caption", status="failed", error=error_msg, lease_token=lease_token)
            emit_event(
                service=_SERVICE_NAME,
                event_name="caption_failed",
                category="job_failure",
                level="ERROR",
                org_id=org_id,
                job_id=file_id,
                duration_ms=int((time.monotonic() - t_start) * 1000),
                message=error_msg[:1000],
                metadata={
                    "video_id": video_id,
                    "stage": "reingest",
                    "error_class": type(e).__name__,
                    "error_msg": str(e)[:500],
                },
            )
            return

        _safe_update_job_status(api_client, video_id, file_id, job_type="caption", status="done", lease_token=lease_token)

        logger.info(
            "caption_processing_complete",
            extra={
                "org_id": org_id_str,
                "video_id": video_id,
                "scene_count": scene_count,
                "frames_processed": len(downloaded_keyframes),
                "frames_with_caption": frames_with_caption,
                "total_caption_chars": total_caption_chars,
                "caption_duration_ms": int((time.monotonic() - caption_started) * 1000),
                "updated_count": ingest_result.get("updated_count", 0),
            },
        )

        emit_event(
            service=_SERVICE_NAME,
            event_name="caption_completed",
            category="job_success",
            level="INFO",
            org_id=org_id,
            job_id=file_id,
            duration_ms=int((time.monotonic() - t_start) * 1000),
            metadata={
                "video_id": video_id,
                "scene_count": scene_count,
                "frames_processed": len(downloaded_keyframes),
                "frames_with_caption": frames_with_caption,
                "total_caption_chars": total_caption_chars,
            },
        )

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        _safe_update_job_status(api_client, video_id, file_id, job_type="caption", status="failed", error=error_msg, lease_token=lease_token)
        logger.exception(
            "caption_processing_failed",
            extra={"org_id": org_id_str, "video_id": video_id},
        )
        emit_event(
            service=_SERVICE_NAME,
            event_name="caption_failed",
            category="job_failure",
            level="ERROR",
            org_id=org_id,
            job_id=file_id,
            duration_ms=int((time.monotonic() - t_start) * 1000),
            message=error_msg[:1000],
            metadata={
                "video_id": video_id,
                "error_class": type(e).__name__,
                "error_msg": str(e)[:500],
            },
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


ENRICH_BATCH_SIZE = 200


def _post_enrich_to_api(
    settings: Any,
    org_id: Any,
    video_id: str,
    scenes: list[dict[str, Any]],
) -> dict[str, Any]:
    requests = importlib.import_module("requests")

    enrich_scenes = []
    for scene in scenes:
        if scene.get("scene_caption"):
            enrich_scenes.append(
                {
                    "scene_id": scene["scene_id"],
                    "scene_caption": scene["scene_caption"],
                }
            )

    if not enrich_scenes:
        return {"updated_count": 0, "video_id": video_id}

    api_base = settings.drive_api_base_url.rstrip("/")
    url = f"{api_base}/internal/ingest/enrich"
    headers = {
        "Authorization": f"Bearer {settings.drive_internal_api_key}",
        "X-Heimdex-Org-Id": str(org_id),
        "Content-Type": "application/json",
    }

    total_updated = 0
    for batch_start in range(0, len(enrich_scenes), ENRICH_BATCH_SIZE):
        batch = enrich_scenes[batch_start : batch_start + ENRICH_BATCH_SIZE]
        payload = {"video_id": video_id, "scenes": batch}

        resp = requests.post(url, json=payload, headers=headers, timeout=300)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Internal enrich API returned {resp.status_code}: {resp.text[:500]}"
            )
        total_updated += resp.json().get("updated_count", 0)

    return {"updated_count": total_updated, "video_id": video_id}


def _process_single_scene_caption(
    api_client: Any,
    settings: Any,
    scene_job: Any,
    caption_engine: Any = None,
) -> None:
    """Process a single scene from a v2 per-scene SQS message.

    Unlike ``_process_single_caption`` (v1, per-video), this:
    - Downloads ONE keyframe directly via ``scene_job.keyframe_s3_key``
    - Generates a caption for that single keyframe
    - Posts the result to the enrich API for that scene only
    - Does NOT update per-video job status (SQS handles per-scene retries)
    """
    S3Client = importlib.import_module("heimdex_worker_sdk.s3").S3Client

    org_id = scene_job.org_id
    org_id_str = str(org_id)
    video_id = scene_job.video_id
    scene_id = scene_job.scene_id
    keyframe_s3_key = scene_job.keyframe_s3_key
    temp_dir = Path(tempfile.mkdtemp(prefix=f"caption_scene_{scene_id}_"))

    t_start = time.monotonic()

    try:
        s3 = S3Client(bucket=settings.drive_s3_bucket)

        # Download single keyframe from S3
        keyframe_path = temp_dir / f"{scene_id}.jpg"
        try:
            s3.download_file(keyframe_s3_key, keyframe_path)
        except Exception:
            logger.warning(
                "scene_caption_keyframe_download_failed",
                extra={
                    "org_id": org_id_str,
                    "video_id": video_id,
                    "scene_id": scene_id,
                    "s3_key": keyframe_s3_key,
                },
                exc_info=True,
            )
            raise  # Let SQS retry via visibility timeout

        # Initialize caption engine if needed
        engine = caption_engine
        if engine is None:
            _create = importlib.import_module(
                "heimdex_media_pipelines.vision"
            ).create_caption_engine
            engine = _create(
                model=getattr(settings, "caption_engine", "qwen2vl"),
                use_gpu=settings.use_gpu,
            )

        # Determine prompt: VLM tags or standard caption
        vlm_tags_enabled = getattr(scene_job, "vlm_tags_enabled", False)
        transcript_raw = getattr(scene_job, "transcript_raw", None)

        caption_started = time.monotonic()

        if vlm_tags_enabled:
            # VLM tag extraction: enhanced prompt with transcript context
            tagging_mod = importlib.import_module("heimdex_media_pipelines.vision.tagging")
            tag_parser_mod = importlib.import_module("heimdex_media_contracts.tags.parser")

            tag_prompt = tagging_mod.build_tag_prompt(transcript_raw or "")
            max_tokens = tagging_mod.get_tag_max_tokens()
            result = engine.caption(str(keyframe_path), prompt=tag_prompt)

            if not result.caption:
                logger.info(
                    "scene_caption_empty",
                    extra={"scene_id": scene_id, "video_id": video_id, "vlm_tags": True},
                )
                emit_event(
                    service=_SERVICE_NAME,
                    event_name="caption_skipped",
                    category="job_failure",
                    level="WARNING",
                    org_id=org_id,
                    duration_ms=int((time.monotonic() - t_start) * 1000),
                    message="empty_caption_vlm_tags",
                    metadata={
                        "video_id": video_id,
                        "scene_id": scene_id,
                        "scene_index": scene_job.scene_index,
                        "mode": "vlm_tags",
                        "reason": "empty_caption",
                        "error_class": "EmptyCaption",
                    },
                )
                return

            vlm_result = tag_parser_mod.parse_vlm_tag_output(result.caption)

            enrich_scene: dict[str, Any] = {
                "scene_id": scene_id,
                "scene_caption": vlm_result.caption[:5_000],
            }
            if vlm_result.keyword_tags:
                enrich_scene["keyword_tags"] = vlm_result.keyword_tags
            if vlm_result.product_tags:
                enrich_scene["product_tags"] = vlm_result.product_tags
            if vlm_result.product_entities:
                enrich_scene["product_entities"] = vlm_result.product_entities

            ai_tags_enabled = getattr(scene_job, "ai_tags_enabled", False)
            if ai_tags_enabled and vlm_result.ai_tags:
                enrich_scene["ai_tags"] = vlm_result.ai_tags

            _post_enrich_to_api(
                settings=settings,
                org_id=org_id,
                video_id=video_id,
                scenes=[enrich_scene],
            )

            logger.info(
                "scene_caption_vlm_tags_complete",
                extra={
                    "org_id": org_id_str,
                    "video_id": video_id,
                    "scene_id": scene_id,
                    "scene_index": scene_job.scene_index,
                    "caption_chars": len(vlm_result.caption),
                    "keyword_tags": vlm_result.keyword_tags,
                    "product_tags": vlm_result.product_tags,
                    "product_entities": vlm_result.product_entities,
                    "ai_tags": vlm_result.ai_tags,
                    "ai_tags_enabled": getattr(scene_job, "ai_tags_enabled", False),
                    "parse_success": vlm_result.parse_success,
                    "has_transcript": bool(transcript_raw),
                    "duration_ms": int((time.monotonic() - caption_started) * 1000),
                },
            )
            emit_event(
                service=_SERVICE_NAME,
                event_name="caption_completed",
                category="job_success",
                level="INFO",
                org_id=org_id,
                duration_ms=int((time.monotonic() - t_start) * 1000),
                metadata={
                    "video_id": video_id,
                    "scene_id": scene_id,
                    "scene_index": scene_job.scene_index,
                    "mode": "vlm_tags",
                    "caption_chars": len(vlm_result.caption),
                    "parse_success": vlm_result.parse_success,
                    "has_transcript": bool(transcript_raw),
                },
            )
        else:
            # Standard caption (existing behavior)
            result = engine.caption(str(keyframe_path))

            if not result.caption:
                logger.info(
                    "scene_caption_empty",
                    extra={"scene_id": scene_id, "video_id": video_id},
                )
                emit_event(
                    service=_SERVICE_NAME,
                    event_name="caption_skipped",
                    category="job_failure",
                    level="WARNING",
                    org_id=org_id,
                    duration_ms=int((time.monotonic() - t_start) * 1000),
                    message="empty_caption",
                    metadata={
                        "video_id": video_id,
                        "scene_id": scene_id,
                        "scene_index": scene_job.scene_index,
                        "mode": "standard",
                        "reason": "empty_caption",
                        "error_class": "EmptyCaption",
                    },
                )
                return

            caption_text = result.caption[:5_000]

            _post_enrich_to_api(
                settings=settings,
                org_id=org_id,
                video_id=video_id,
                scenes=[{"scene_id": scene_id, "scene_caption": caption_text}],
            )

            logger.info(
                "scene_caption_complete",
                extra={
                    "org_id": org_id_str,
                    "video_id": video_id,
                    "scene_id": scene_id,
                    "scene_index": scene_job.scene_index,
                    "caption_chars": len(caption_text),
                    "duration_ms": int((time.monotonic() - caption_started) * 1000),
                },
            )
            emit_event(
                service=_SERVICE_NAME,
                event_name="caption_completed",
                category="job_success",
                level="INFO",
                org_id=org_id,
                duration_ms=int((time.monotonic() - t_start) * 1000),
                metadata={
                    "video_id": video_id,
                    "scene_id": scene_id,
                    "scene_index": scene_job.scene_index,
                    "mode": "standard",
                    "caption_chars": len(caption_text),
                },
            )
    except Exception as e:
        logger.exception(
            "scene_caption_failed",
            extra={
                "org_id": org_id_str,
                "video_id": video_id,
                "scene_id": scene_id,
            },
        )
        emit_event(
            service=_SERVICE_NAME,
            event_name="caption_failed",
            category="job_failure",
            level="ERROR",
            org_id=org_id,
            duration_ms=int((time.monotonic() - t_start) * 1000),
            message=f"{type(e).__name__}: {e}"[:1000],
            metadata={
                "video_id": video_id,
                "scene_id": scene_id,
                "scene_index": scene_job.scene_index,
                "error_class": type(e).__name__,
                "error_msg": str(e)[:500],
            },
        )
        raise  # Re-raise so SQS consumer treats this as failure (retry)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)