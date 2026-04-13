"""Shorts render job service layer.

Orchestrates render job CRUD with scene boundary validation,
SQS publishing (fire-and-forget), and S3 cleanup on delete.

Also exposes a module-level ``cleanup_expired_renders`` entry point
used by the nightly cleanup CLI. It lives here (not on the request-scoped
``ShortsRenderService``) so the CLI doesn't have to construct the full
service dependency graph.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, cast
from uuid import UUID

from botocore.exceptions import ClientError
from fastapi import HTTPException, status

from app.config import get_settings
from app.logging_config import get_logger
from app.modules.shorts_render.models import ShortsRenderJob
from app.modules.shorts_render.repository import ShortsRenderJobRepository
from app.modules.shorts_render.schemas import (
    RenderJobCreate,
    RenderJobListResponse,
    RenderJobResponse,
)

logger = get_logger(__name__)


@dataclass
class CleanupResult:
    """Outcome of a single ``cleanup_expired_renders`` invocation.

    - ``total_expired``: jobs matched as expired (with + without output)
    - ``s3_deleted``: S3 objects successfully deleted
    - ``s3_skipped_not_found``: S3 keys that were already gone (idempotent)
    - ``s3_failed``: S3 deletes that raised an unexpected error
    - ``db_deleted``: DB rows removed
    - ``dry_run``: True when nothing was actually deleted
    - ``failed_keys``: list of ``(s3_key, error_message)`` for failed deletes
    """
    total_expired: int = 0
    s3_deleted: int = 0
    s3_skipped_not_found: int = 0
    s3_failed: int = 0
    db_deleted: int = 0
    dry_run: bool = False
    failed_keys: list[tuple[str, str]] = field(default_factory=list)


async def cleanup_expired_renders(
    repository: ShortsRenderJobRepository,
    s3_client: Any,
    *,
    dry_run: bool = False,
    now: datetime | None = None,
) -> CleanupResult:
    """Delete expired shorts-render jobs from S3 and the DB.

    Per-job atomic: a failure on job N does not abort the sweep for jobs
    N+1..end. S3 deletes that return NoSuchKey are treated as already-done
    (idempotent). DB rows are only removed after the corresponding S3
    delete succeeds (or the object was already missing) — never orphan a
    file by deleting the row first.

    Separately drops DB rows for failed/orphaned jobs that never produced
    an S3 output; those would otherwise accumulate forever because
    ``list_expired()`` filters on ``output_s3_key IS NOT NULL``.

    Args:
        repository: bound to an AsyncSession; caller owns the commit
        s3_client: anything with a ``delete(key)`` method. Typed as Any so
            the CLI can pass the real ``S3Client`` while tests pass a mock
            without satisfying an import-time protocol.
        dry_run: when True, iterate and log but do not call S3 or the DB
        now: override wall-clock for tests. Defaults to ``datetime.now(utc)``.
    """
    current_time = now or datetime.now(timezone.utc)
    result = CleanupResult(dry_run=dry_run)

    with_output = await repository.list_expired(current_time)
    without_output = await repository.list_expired_without_output(current_time)
    result.total_expired = len(with_output) + len(without_output)

    if result.total_expired == 0:
        logger.info("cleanup_shorts_renders_noop", now=current_time.isoformat())
        return result

    logger.info(
        "cleanup_shorts_renders_started",
        dry_run=dry_run,
        now=current_time.isoformat(),
        with_output=len(with_output),
        without_output=len(without_output),
    )

    # --- Jobs with output: S3 delete → DB delete ---
    for job in with_output:
        s3_key = job.output_s3_key
        if s3_key is None:
            # list_expired() filters on IS NOT NULL; this is defensive only
            continue

        if dry_run:
            logger.info(
                "cleanup_would_delete",
                job_id=str(job.id),
                s3_key=s3_key,
                expires_at=job.expires_at.isoformat() if job.expires_at else None,
            )
            continue

        try:
            s3_client.delete(s3_key)
            result.s3_deleted += 1
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "404"):
                # Already gone — still fine to drop the DB row
                result.s3_skipped_not_found += 1
                logger.info(
                    "cleanup_s3_already_gone",
                    job_id=str(job.id),
                    s3_key=s3_key,
                )
            else:
                result.s3_failed += 1
                result.failed_keys.append((s3_key, str(e)))
                logger.warning(
                    "cleanup_s3_delete_failed",
                    job_id=str(job.id),
                    s3_key=s3_key,
                    error=str(e),
                )
                # Skip DB delete so the row stays and we can retry next run
                continue

        deleted = await repository.delete_one_by_id_internal(cast(UUID, job.id))
        if deleted:
            result.db_deleted += 1

    # --- Failed / orphaned jobs: DB delete only (no S3 key to touch) ---
    for job in without_output:
        if dry_run:
            logger.info(
                "cleanup_would_delete_db_only",
                job_id=str(job.id),
                status=job.status,
                expires_at=job.expires_at.isoformat() if job.expires_at else None,
            )
            continue

        deleted = await repository.delete_one_by_id_internal(cast(UUID, job.id))
        if deleted:
            result.db_deleted += 1

    logger.info(
        "cleanup_shorts_renders_completed",
        dry_run=dry_run,
        total_expired=result.total_expired,
        s3_deleted=result.s3_deleted,
        s3_skipped_not_found=result.s3_skipped_not_found,
        s3_failed=result.s3_failed,
        db_deleted=result.db_deleted,
    )

    return result


def _to_response(job: ShortsRenderJob, download_url: str | None = None) -> RenderJobResponse:
    # Extract thumbnail from first scene clip in input_spec
    thumb_vid = None
    thumb_scene = None
    try:
        clips = job.input_spec.get("scene_clips", [])
        if clips:
            thumb_vid = clips[0].get("video_id")
            thumb_scene = clips[0].get("scene_id")
    except (AttributeError, IndexError, TypeError):
        pass

    return RenderJobResponse(
        id=cast(UUID, job.id),
        video_id=job.video_id,
        title=job.title,
        status=job.status,
        created_at=job.created_at,
        completed_at=job.completed_at,
        render_time_ms=job.render_time_ms,
        output_duration_ms=job.output_duration_ms,
        output_size_bytes=job.output_size_bytes,
        error=job.error,
        download_url=download_url,
        thumbnail_video_id=thumb_vid,
        thumbnail_scene_id=thumb_scene,
    )


class ShortsRenderService:
    def __init__(self, repository: ShortsRenderJobRepository, scene_search: Any):
        self.repository = repository
        self.scene_search = scene_search

    async def create_render_job(
        self,
        org_id: UUID,
        user_id: UUID,
        payload: RenderJobCreate,
    ) -> RenderJobResponse:
        """Create a render job after validating scene boundaries."""
        # 1. Validate scene boundaries via OpenSearch mget
        await self._validate_scene_clips(org_id, payload)

        # 2. Create DB record
        settings = get_settings()
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.shorts_render_expiry_days)

        job = await self.repository.create(
            org_id=org_id,
            user_id=user_id,
            video_id=payload.video_id,
            title=payload.title,
            input_spec=payload.composition.model_dump(),
            expires_at=expires_at,
        )

        logger.info(
            "render_job_created",
            job_id=str(job.id),
            org_id=str(org_id),
            user_id=str(user_id),
            video_id=payload.video_id,
            clip_count=len(payload.composition.scene_clips),
            subtitle_count=len(payload.composition.subtitles),
        )

        # 3. Publish SQS — if this fails, mark job as failed so it doesn't
        #    stay stuck in "queued" forever.
        try:
            from app.sqs_producer import publish_shorts_render_job

            publish_shorts_render_job(
                job_id=cast(UUID, job.id),
                org_id=org_id,
                video_id=payload.video_id,
                input_spec=payload.composition.model_dump(),
            )
        except Exception:
            logger.exception("sqs_shorts_render_publish_failed", job_id=str(job.id))
            await self.repository.update_status(
                cast(UUID, job.id),
                "failed",
                error="Failed to enqueue render job",
            )
            job.status = "failed"
            job.error = "Failed to enqueue render job"

        return _to_response(job)

    async def get_render_job_record(
        self,
        org_id: UUID,
        job_id: UUID,
    ) -> ShortsRenderJob | None:
        """Get the raw DB record for a render job."""
        return await self.repository.get_by_id(org_id, job_id)

    async def get_render_job(
        self,
        org_id: UUID,
        job_id: UUID,
    ) -> RenderJobResponse:
        """Get a render job by ID. Populates download_url for completed jobs."""
        job = await self.repository.get_by_id(org_id, job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Render job not found",
            )

        download_url: str | None = None
        if job.status == "completed" and job.output_s3_key:
            download_url = f"/api/shorts/render/{job.id}/download"

        return _to_response(job, download_url=download_url)

    async def list_render_jobs(
        self,
        org_id: UUID,
        user_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> RenderJobListResponse:
        """List render jobs for a user with pagination."""
        jobs, total = await self.repository.list_by_user(org_id, user_id, limit, offset)
        return RenderJobListResponse(
            items=[_to_response(job) for job in jobs],
            total=total,
        )

    async def delete_render_job(
        self,
        org_id: UUID,
        job_id: UUID,
    ) -> None:
        """Delete a render job. Cleans up S3 output if present."""
        job = await self.repository.get_by_id(org_id, job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Render job not found",
            )

        # Clean up S3 output if it exists
        if job.output_s3_key:
            try:
                from app.storage.s3 import S3Client

                settings = get_settings()
                s3 = S3Client(bucket=settings.drive_s3_bucket)
                s3.delete(job.output_s3_key)
            except Exception:
                logger.exception(
                    "s3_render_output_delete_failed",
                    job_id=str(job_id),
                    s3_key=job.output_s3_key,
                )

        await self.repository.delete(org_id, job_id)

    async def _validate_scene_clips(
        self,
        org_id: UUID,
        payload: RenderJobCreate,
    ) -> None:
        """Validate that all scene clips fall within their scene boundaries."""
        clips = payload.composition.scene_clips

        # Build composite doc IDs matching OpenSearch pattern
        doc_ids = [f"{org_id}:{clip.scene_id}" for clip in clips]

        # Batch-fetch all scenes from OpenSearch
        scenes = await self.scene_search.mget_scenes(doc_ids)

        for i, clip in enumerate(clips):
            doc_id = f"{org_id}:{clip.scene_id}"
            scene = scenes.get(doc_id)

            if scene is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"scene_clip[{i}]: scene '{clip.scene_id}' not found",
                )

            scene_start = scene.get("start_ms", 0)
            scene_end = scene.get("end_ms", 0)

            if clip.start_ms < scene_start:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=(
                        f"scene_clip[{i}]: start_ms out of scene bounds "
                        f"(clip: {clip.start_ms}-{clip.end_ms}, "
                        f"scene: {scene_start}-{scene_end})"
                    ),
                )

            if clip.end_ms > scene_end:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=(
                        f"scene_clip[{i}]: end_ms out of scene bounds "
                        f"(clip: {clip.start_ms}-{clip.end_ms}, "
                        f"scene: {scene_start}-{scene_end})"
                    ),
                )
