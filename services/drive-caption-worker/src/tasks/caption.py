import importlib
import json
import logging
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


async def process_caption_pending_files(session: Any, settings: Any, caption_engine: Any = None) -> None:
    importlib.import_module("app.db.models")
    drive_repository = importlib.import_module("app.modules.drive.repository")
    file_repo = drive_repository.DriveFileRepository(session)
    files = await file_repo.claim_caption_pending_files(limit=1)

    for drive_file in files:
        await _process_single_caption(
            session=session,
            settings=settings,
            drive_file=drive_file,
            file_repo=file_repo,
            caption_engine=caption_engine,
        )


async def _process_single_caption(
    session: Any,
    settings: Any,
    drive_file: Any,
    file_repo: Any,
    caption_engine: Any = None,
) -> None:
    drive_keys = importlib.import_module("app.modules.drive.keys")
    scene_manifest_s3_key = drive_keys.scene_manifest_s3_key
    enrichment_keyframe_s3_key = drive_keys.enrichment_keyframe_s3_key
    S3Client = importlib.import_module("app.storage.s3").S3Client

    _ = session
    org_id = drive_file.org_id
    org_id_str = str(org_id)
    video_id = drive_file.video_id
    temp_dir = Path(tempfile.mkdtemp(prefix=f"caption_{video_id}_"))

    try:
        s3 = S3Client(bucket=settings.drive_s3_bucket)
        manifest_key = scene_manifest_s3_key(org_id_str, video_id)
        manifest_path = temp_dir / "scenes.json"

        try:
            s3.download_file(manifest_key, manifest_path)
        except Exception as e:
            error_msg = f"manifest_download_failed: {type(e).__name__}: {e}"
            await file_repo.update_caption_enrichment_status(
                drive_file.id,
                caption_status="failed",
                caption_error=error_msg,
            )
            return

        manifest = json.loads(manifest_path.read_text())
        scenes = manifest.get("scenes", [])
        scene_count = len(scenes)

        if scene_count == 0:
            await file_repo.update_caption_enrichment_status(drive_file.id, caption_status="done")
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

        # Parallel S3 keyframe downloads + pipelined inference.
        # All downloads fire at once; inference starts as each frame arrives.
        # While the model processes frame N (~15s), remaining downloads
        # complete in the background — no wasted I/O wait.
        caption_started = time.monotonic()
        if caption_engine is None:
            _create = importlib.import_module("heimdex_media_pipelines.vision").create_caption_engine
            caption_engine = _create(model="internvl2", use_gpu=False)
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
                    # Pipeline: start inference immediately while other
                    # downloads continue in the background threads.
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
            await file_repo.update_caption_enrichment_status(
                drive_file.id,
                caption_status="failed",
                caption_error="no_keyframes_downloaded",
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

        video_title = manifest.get("video_title", getattr(drive_file, "file_name", ""))
        library_id = manifest.get("library_id", getattr(drive_file, "library_id", None))
        duration_ms = manifest.get("total_duration_ms", getattr(drive_file, "proxy_duration_ms", 0))

        try:
            ingest_result = _post_scenes_to_api(
                settings=settings,
                org_id=org_id,
                video_id=video_id,
                video_title=video_title,
                library_id=library_id,
                duration_ms=duration_ms,
                scenes=updated_scenes,
            )
        except Exception as e:
            error_msg = f"caption_reingest_failed: {type(e).__name__}: {e}"
            await file_repo.update_caption_enrichment_status(
                drive_file.id,
                caption_status="failed",
                caption_error=error_msg,
            )
            return

        await file_repo.update_caption_enrichment_status(drive_file.id, caption_status="done")

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
                "indexed_count": ingest_result.get("indexed_count", 0),
            },
        )

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        await file_repo.update_caption_enrichment_status(
            drive_file.id,
            caption_status="failed",
            caption_error=error_msg,
        )
        logger.exception(
            "caption_processing_failed",
            extra={"org_id": org_id_str, "video_id": video_id},
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _post_scenes_to_api(
    settings: Any,
    org_id: Any,
    video_id: str,
    video_title: str,
    library_id: Any,
    duration_ms: int,
    scenes: list[dict[str, Any]],
) -> dict[str, Any]:
    requests = importlib.import_module("requests")

    payload = {
        "video_id": video_id,
        "video_title": video_title,
        "library_id": str(library_id),
        "total_duration_ms": duration_ms,
        "scenes": scenes,
    }

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
        timeout=120,
    )

    if resp.status_code != 200:
        raise RuntimeError(
            f"Internal ingest API returned {resp.status_code}: {resp.text[:500]}"
        )

    return resp.json()
