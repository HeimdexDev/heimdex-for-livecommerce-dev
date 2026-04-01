"""Shorts render job service layer.

Orchestrates render job CRUD with scene boundary validation,
SQS publishing (fire-and-forget), and S3 cleanup on delete.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, cast
from uuid import UUID

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
