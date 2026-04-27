"""Render task orchestration — download, render, upload, report.

All ffmpeg logic is delegated to heimdex-media-pipelines.
All schema definitions come from heimdex-media-contracts.
This module is strictly orchestration: download → call pipeline → upload → report.
"""

import importlib
import logging
import os
import shutil
import tempfile
from pathlib import Path

from src.message_adapter import RenderJobMessage

logger = logging.getLogger(__name__)

_DEFAULT_FONT_DIR = "/fonts"

# Lazy-loaded at first use (avoids import errors when testing in isolation)
CompositionSpec = None
S3Client = None
render_composition = None


def _ensure_imports() -> None:
    """Load heavy dependencies on first call."""
    global CompositionSpec, S3Client, render_composition
    if CompositionSpec is None:
        CompositionSpec = importlib.import_module(
            "heimdex_media_contracts.composition"
        ).CompositionSpec
    if S3Client is None:
        S3Client = importlib.import_module(
            "heimdex_worker_sdk.s3"
        ).S3Client
    if render_composition is None:
        render_composition = importlib.import_module(
            "heimdex_media_pipelines.composition"
        ).render_composition


def _report_status(
    api_client,
    org_id: str,
    job_id: str,
    *,
    status: str,
    output_s3_key: str | None = None,
    output_duration_ms: int | None = None,
    output_size_bytes: int | None = None,
    render_time_ms: int | None = None,
    error: str | None = None,
) -> None:
    """Report render job status to the API via internal endpoint."""
    url = f"{api_client.base_url.rstrip('/')}/internal/shorts-render/{job_id}/status"
    payload: dict = {"status": status}
    if output_s3_key is not None:
        payload["output_s3_key"] = output_s3_key
    if output_duration_ms is not None:
        payload["output_duration_ms"] = output_duration_ms
    if output_size_bytes is not None:
        payload["output_size_bytes"] = output_size_bytes
    if render_time_ms is not None:
        payload["render_time_ms"] = render_time_ms
    if error is not None:
        payload["error"] = error[:2000]

    resp = api_client._session.put(
        url,
        json=payload,
        headers={"X-Heimdex-Org-Id": org_id},
        timeout=30,
    )
    resp.raise_for_status()


def _download_media(
    api_client,
    s3_client,
    org_id: str,
    video_id: str,
    work_dir: str,
) -> str:
    """Download video file to work_dir. Returns local path."""
    url = f"{api_client.base_url.rstrip('/')}/internal/shorts-render/{video_id}/media-source"
    resp = api_client._session.get(
        url,
        headers={"X-Heimdex-Org-Id": org_id},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    source_type = data.get("source_type", "")
    if source_type != "gdrive":
        raise ValueError(f"Unsupported source type: {source_type} for video {video_id}")

    proxy_s3_key = data.get("proxy_s3_key")
    if not proxy_s3_key:
        raise ValueError(f"No proxy S3 key for video {video_id}")

    local_path = Path(work_dir) / f"{video_id}.mp4"
    s3_client.download_file(proxy_s3_key, local_path)
    return str(local_path)


def _upload_rendered_file(
    s3_client,
    local_path: str,
    org_id: str,
    job_id: str,
) -> tuple[str, int]:
    """Upload rendered MP4 to S3. Returns (s3_key, file_size_bytes)."""
    s3_key = f"{org_id}/shorts/renders/{job_id}/output.mp4"
    file_size = os.path.getsize(local_path)
    s3_client.upload_file(Path(local_path), s3_key, content_type="video/mp4")
    return s3_key, file_size


def process_render_job(*, api_client, settings, render_job: RenderJobMessage) -> None:
    """Full render pipeline — called by SQS callback.

    1. Report status='rendering' to API
    2. Parse input_spec as CompositionSpec
    3. Download media for each clip
    4. Call render_composition() from heimdex-media-pipelines
    5. Upload rendered MP4 to S3
    6. Report status='completed' to API (or 'failed' on error)
    """
    _ensure_imports()

    job_id = render_job.job_id
    org_id = render_job.org_id

    work_dir = tempfile.mkdtemp(prefix=f"shorts_render_{job_id}_")

    try:
        # 1. Report rendering status
        _report_status(api_client, org_id, job_id, status="rendering")

        # 2. Parse composition spec
        spec = CompositionSpec(**render_job.input_spec)

        logger.info(
            "render_started",
            extra={
                "job_id": job_id,
                "org_id": org_id,
                "clip_count": len(spec.scene_clips),
                "subtitle_count": len(spec.subtitles),
            },
        )

        # 3. Download media for each unique video_id
        s3_client = S3Client(bucket=settings.drive_s3_bucket)

        media_paths: dict[str, str] = {}
        for i, clip in enumerate(spec.scene_clips):
            if clip.video_id not in media_paths:
                media_paths[clip.video_id] = _download_media(
                    api_client, s3_client, org_id, clip.video_id, work_dir,
                )
                logger.info(
                    "clip_extracted",
                    extra={
                        "job_id": job_id,
                        "clip_index": i,
                        "video_id": clip.video_id,
                        "duration_ms": clip.end_ms - clip.start_ms,
                    },
                )

        # 4. Render composition
        font_dir = os.environ.get("FONT_DIR", _DEFAULT_FONT_DIR)
        use_gpu = getattr(settings, "use_gpu", False)
        output_path = os.path.join(work_dir, "output.mp4")

        logger.info(
            "ffmpeg_encode_started",
            extra={
                "job_id": job_id,
                "clip_count": len(spec.scene_clips),
                "subtitle_count": len(spec.subtitles),
                "use_gpu": use_gpu,
            },
        )

        result = render_composition(
            spec=spec,
            media_paths=media_paths,
            output_path=output_path,
            font_dir=font_dir,
            use_gpu=use_gpu,
        )

        # 5. Upload to S3
        s3_key, file_size = _upload_rendered_file(
            s3_client, output_path, org_id, job_id,
        )

        # 6. Report completed
        _report_status(
            api_client,
            org_id,
            job_id,
            status="completed",
            output_s3_key=s3_key,
            output_duration_ms=result.duration_ms,
            output_size_bytes=result.size_bytes,
            render_time_ms=result.render_time_ms,
        )

        logger.info(
            "render_completed",
            extra={
                "job_id": job_id,
                "s3_key": s3_key,
                "duration_ms": result.duration_ms,
                "output_size": result.size_bytes,
                "render_time_ms": result.render_time_ms,
            },
        )

    except Exception as exc:
        logger.error(
            "render_failed",
            extra={"job_id": job_id, "error": str(exc)},
            exc_info=True,
        )
        try:
            _report_status(
                api_client,
                org_id,
                job_id,
                status="failed",
                error=str(exc),
            )
        except Exception:
            logger.exception("render_status_update_failed", extra={"job_id": job_id})

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
