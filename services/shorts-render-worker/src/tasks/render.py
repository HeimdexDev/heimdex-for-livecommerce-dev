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
import time
from pathlib import Path

from heimdex_worker_sdk import emit_event

from src.message_adapter import RenderJobMessage

logger = logging.getLogger(__name__)
_SERVICE_NAME = "shorts-render-worker"

_DEFAULT_FONT_DIR = "/usr/share/fonts/heimdex"

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


def _check_job_alive(api_client, job_id: str) -> bool:
    """Probe the api to confirm the render job row still exists.

    Hits ``GET /internal/shorts-render/{job_id}/exists``:
        * 200 → row alive, return True
        * 404 → row deleted (UI delete, cleanup cron), return False
        * any other code or network error → fail-open, return True

    Why fail-open: a transient api outage shouldn't cause us to drop
    a real render request. Over-rendering once is recoverable; the
    api's idempotent ``complete_idempotent`` handles a duplicate
    completion message safely. Under-rendering would silently lose
    the user's render with no surfaced error.

    Returning False from this function lets the SDK ack the SQS
    message via normal task-success path — message is removed from
    the queue, no orphan S3 file is uploaded.
    """
    url = f"{api_client.base_url.rstrip('/')}/internal/shorts-render/{job_id}/exists"
    try:
        resp = api_client._session.get(url, timeout=10)
    except Exception:  # noqa: BLE001 — fail-open on any transport error
        logger.warning(
            "render_job_alive_check_transport_error",
            extra={"job_id": job_id},
            exc_info=True,
        )
        return True
    if resp.status_code == 200:
        return True
    if resp.status_code == 404:
        return False
    # Unexpected status — log and fail-open. Don't burn the job on a
    # 500 from an unrelated issue.
    logger.warning(
        "render_job_alive_check_unexpected_status",
        extra={"job_id": job_id, "status_code": resp.status_code},
    )
    return True


def process_render_job(*, api_client, settings, render_job: RenderJobMessage) -> None:
    """Full render pipeline — called by SQS callback.

    1. Report status='rendering' to API
    2. Parse input_spec as CompositionSpec
    3. Download media for each clip
    4. Call render_composition() from heimdex-media-pipelines
    5. Upload rendered MP4 to S3
    6. Report status='completed' to API (or 'failed' on error)
    """
    job_id = render_job.job_id
    org_id = render_job.org_id

    # 0. Liveness probe — bail out cleanly if the row was deleted
    # between SQS publish and worker receive. Avoids an orphan S3
    # output and the noisy ``PUT /status`` 404 storm that the
    # post-delete render path otherwise generates. Fail-open on
    # transport errors so a transient api outage doesn't drop real
    # work — see ``_check_job_alive`` docstring.
    #
    # Runs BEFORE ``_ensure_imports`` so we don't pay the ML
    # contract+pipeline import cost on jobs we're about to skip.
    if not _check_job_alive(api_client, job_id):
        logger.info(
            "render_skipped_job_deleted",
            extra={
                "job_id": job_id,
                "org_id": org_id,
                "reason": "db_row_missing_pre_render",
            },
        )
        # Returning normally lets the SDK ack the SQS message →
        # message is removed from the queue. No render work, no
        # status PUT, no S3 upload.
        return

    # Heavy ML+contracts imports happen AFTER the alive check so
    # skipped jobs pay zero import cost.
    _ensure_imports()

    work_dir = tempfile.mkdtemp(prefix=f"shorts_render_{job_id}_")

    t_start = time.monotonic()

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
        emit_event(
            service=_SERVICE_NAME,
            event_name="render_completed",
            category="job_success",
            level="INFO",
            org_id=org_id,
            job_id=job_id,
            duration_ms=int((time.monotonic() - t_start) * 1000),
            metadata={
                "s3_key": s3_key,
                "output_duration_ms": result.duration_ms,
                "output_size_bytes": result.size_bytes,
                "render_time_ms": result.render_time_ms,
                "clip_count": len(spec.scene_clips),
                "subtitle_count": len(spec.subtitles),
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
        emit_event(
            service=_SERVICE_NAME,
            event_name="render_failed",
            category="job_failure",
            level="ERROR",
            org_id=org_id,
            job_id=job_id,
            duration_ms=int((time.monotonic() - t_start) * 1000),
            message=f"{type(exc).__name__}: {exc}"[:1000],
            metadata={
                "error_class": type(exc).__name__,
                "error_msg": str(exc)[:500],
            },
        )

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
