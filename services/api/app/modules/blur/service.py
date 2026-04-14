"""Blur job service layer.

Orchestrates DB writes, SQS publishes, and (on delete) S3 cleanup.
Never touches OpenSearch — blur output is stored in S3 only; indexing
detections into the scene index is a deferred follow-up PR.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, cast
from uuid import UUID

from fastapi import HTTPException, status

from app.config import get_settings
from app.logging_config import get_logger
from app.modules.blur.models import (
    BLUR_STATUS_DONE,
    BLUR_STATUS_FAILED,
    BLUR_STATUS_QUEUED,
    BlurJob,
)
from app.modules.blur.repository import BlurJobRepository
from app.modules.blur.schemas import (
    BlurJobListResponse,
    BlurJobResponse,
    CreateBlurJobRequest,
)
from app.modules.drive.repository import DriveFileRepository

logger = get_logger(__name__)


# How long a just-created blur job is visible to the dedupe query.
# Short — a user intentionally re-submitting the same blur options on
# the same video is rare, but double-click debounce is common.
_DEDUPE_WINDOW_SECONDS = 30


def compute_options_hash(options: Any) -> str:
    """Deterministic sha256 of a BlurOptions payload."""
    if hasattr(options, "model_dump"):
        body = options.model_dump()
    else:
        body = options
    canonical = json.dumps(body, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# Presigned URL TTL for playback / manifest / mask fetches exposed to
# the frontend. 1 hour matches how long a typical blur-detail-page
# session lasts; the frontend refetches on mount.
_BLUR_ARTIFACT_URL_TTL_SECONDS = 3600


def _to_response(job: BlurJob) -> BlurJobResponse:
    """Sync view — no presigned URLs. Used for freshly-created rows
    where URL generation would be wasted (queued, nothing to serve).
    """
    return BlurJobResponse(
        id=cast(UUID, job.id),
        file_id=job.file_id,
        video_id=job.video_id,
        requested_by=job.requested_by,
        status=job.status,
        options=job.options,
        source_kind=job.source_kind,
        blurred_s3_key=job.blurred_s3_key,
        manifest_s3_key=job.manifest_s3_key,
        mask_s3_keys=job.mask_s3_keys,
        detections_summary=job.detections_summary,
        error=job.error,
        progress_pct=job.progress_pct,
        phase=job.phase,
        requested_at=job.requested_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


async def _to_response_presigned(job: BlurJob) -> BlurJobResponse:
    """Async view — populates ``blurred_playback_url``, ``manifest_url``,
    and ``mask_urls`` for done jobs.

    Loose coupling: presigned URL generation is isolated in this helper
    so callers that don't need URLs (create, cancel) stay synchronous
    and cheap. All three URLs are best-effort — a transient S3 hiccup
    yields ``None`` rather than 500-ing the whole list endpoint.
    """
    resp = _to_response(job)
    if job.status != BLUR_STATUS_DONE:
        return resp

    try:
        from app.storage.s3 import S3Client

        settings = get_settings()
        s3 = S3Client(bucket=settings.drive_s3_bucket)
    except Exception:
        logger.exception("blur_s3_client_failed", job_id=str(job.id))
        return resp

    async def _presign(key: str | None) -> str | None:
        if not key:
            return None
        try:
            return await s3.generate_presigned_url_async(
                key, expires_in=_BLUR_ARTIFACT_URL_TTL_SECONDS,
            )
        except Exception:
            logger.exception("blur_presign_failed", job_id=str(job.id), s3_key=key)
            return None

    resp.blurred_playback_url = await _presign(job.blurred_s3_key)
    resp.manifest_url = await _presign(job.manifest_s3_key)
    if job.mask_s3_keys:
        mask_urls: dict[str, str] = {}
        for category, key in job.mask_s3_keys.items():
            url = await _presign(key)
            if url is not None:
                mask_urls[category] = url
        resp.mask_urls = mask_urls or None
    return resp


class BlurService:
    def __init__(
        self,
        repository: BlurJobRepository,
        drive_file_repo: DriveFileRepository,
    ) -> None:
        self.repository = repository
        self.drive_file_repo = drive_file_repo

    # ---------- public (user-facing) ----------

    async def create_blur_job(
        self,
        *,
        org_id: UUID,
        user_id: UUID,
        file_id: UUID,
        payload: CreateBlurJobRequest,
    ) -> BlurJobResponse:
        settings = get_settings()
        if not settings.blur_enabled:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Blur feature is disabled",
            )

        # 1. Resolve the video and its proxy key via the existing
        #    drive-file repository. Org-scoped — a user cannot request
        #    blur on a file in another org.
        drive_file = await self.drive_file_repo.get_by_id(file_id, org_id)
        if drive_file is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Video not found",
            )
        if not drive_file.proxy_s3_key:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Video has no proxy yet — blur requires a completed "
                    "transcode. Retry once the video is indexed."
                ),
            )

        # 2. Concurrency cap. If the org already has >= N jobs in flight,
        #    reject before creating a new row.
        active_count = await self.repository.count_active_for_org(org_id)
        if active_count >= settings.blur_max_active_per_org:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Too many active blur jobs for org "
                    f"({active_count}/{settings.blur_max_active_per_org}). "
                    f"Wait for existing jobs to finish."
                ),
            )

        # 3. Idempotency / dedupe. If an identical request was submitted
        #    within the window, return the existing job.
        options_hash = compute_options_hash(payload.options)
        dedupe_since = datetime.now(timezone.utc) - timedelta(seconds=_DEDUPE_WINDOW_SECONDS)
        existing = await self.repository.find_recent_duplicate(
            org_id=org_id,
            file_id=file_id,
            options_hash=options_hash,
            since=dedupe_since,
        )
        if existing is not None:
            logger.info(
                "blur_job_idempotent_replay",
                job_id=str(existing.id),
                org_id=str(org_id),
                user_id=str(user_id),
                options_hash=options_hash,
            )
            return _to_response(existing)

        # 4. Create the row.
        job = await self.repository.create(
            org_id=org_id,
            file_id=file_id,
            video_id=drive_file.video_id,
            requested_by=user_id,
            options=payload.options.model_dump(),
            options_hash=options_hash,
            source_s3_key=drive_file.proxy_s3_key,
            source_kind=payload.source_kind,
        )

        logger.info(
            "blur_job_created",
            job_id=str(job.id),
            org_id=str(org_id),
            user_id=str(user_id),
            file_id=str(file_id),
            video_id=drive_file.video_id,
            options_hash=options_hash,
        )

        # 5. Publish to SQS. If publish fails, mark the job failed so
        #    the user sees the failure instead of a permanent "queued".
        try:
            from app.sqs_producer import publish_blur_job

            publish_blur_job(
                job_id=cast(UUID, job.id),
                file_id=file_id,
                org_id=org_id,
                video_id=drive_file.video_id,
                proxy_s3_key=drive_file.proxy_s3_key,
                options=payload.options.model_dump(),
            )
        except Exception:
            logger.exception("sqs_blur_publish_failed", job_id=str(job.id))
            # We just created the row — a lease has not been handed out
            # yet — so we can atomically mark it failed via the same
            # row_id without lease check.
            from sqlalchemy import update

            await self.repository.session.execute(
                update(BlurJob)
                .where(BlurJob.id == job.id)
                .values(
                    status=BLUR_STATUS_FAILED,
                    error="Failed to enqueue blur job",
                    completed_at=datetime.now(timezone.utc),
                )
            )
            await self.repository.session.flush()
            job.status = BLUR_STATUS_FAILED
            job.error = "Failed to enqueue blur job"

        return _to_response(job)

    async def get_blur_job(
        self,
        *,
        org_id: UUID,
        job_id: UUID,
    ) -> BlurJobResponse:
        job = await self.repository.get_by_id(org_id, job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Blur job not found",
            )
        return await _to_response_presigned(job)

    async def list_blur_jobs_for_file(
        self,
        *,
        org_id: UUID,
        file_id: UUID,
        limit: int,
        offset: int,
    ) -> BlurJobListResponse:
        jobs, total = await self.repository.list_by_file(org_id, file_id, limit, offset)
        items = [await _to_response_presigned(j) for j in jobs]
        return BlurJobListResponse(
            items=items,
            total=total,
        )

    async def cancel_blur_job(
        self,
        *,
        org_id: UUID,
        job_id: UUID,
    ) -> BlurJobResponse:
        """Cancel a queued job. Running jobs are NOT cancellable — the
        product decision is to let in-flight Aircloud work finish and
        let the user delete the output afterward.
        """
        job = await self.repository.get_by_id(org_id, job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Blur job not found",
            )
        if job.status != BLUR_STATUS_QUEUED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot cancel a job in status={job.status!r}. "
                    f"Only queued jobs can be cancelled."
                ),
            )
        ok = await self.repository.mark_cancelled_if_queued(
            org_id=org_id, job_id=job_id,
        )
        if not ok:
            # Raced with a worker claim between our read and our update.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Job was just claimed by a worker — too late to cancel.",
            )
        refreshed = await self.repository.get_by_id(org_id, job_id)
        assert refreshed is not None
        logger.info("blur_job_cancelled", job_id=str(job_id), org_id=str(org_id))
        return _to_response(refreshed)

    async def delete_blur_job(
        self,
        *,
        org_id: UUID,
        job_id: UUID,
    ) -> None:
        """Delete a completed/failed/cancelled blur job and its S3 outputs.

        The row stays in ``done``/``failed``/``cancelled`` state. Active
        jobs (queued/running) can't be deleted — users must cancel first.
        """
        job = await self.repository.get_by_id(org_id, job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Blur job not found",
            )
        if job.status not in (BLUR_STATUS_DONE, BLUR_STATUS_FAILED, "cancelled"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot delete an active job — cancel it first.",
            )

        if job.blurred_s3_key or job.manifest_s3_key or job.mask_s3_keys:
            try:
                from app.storage.s3 import S3Client
                settings = get_settings()
                s3 = S3Client(bucket=settings.drive_s3_bucket)
                keys_to_delete: list[str] = []
                if job.blurred_s3_key:
                    keys_to_delete.append(job.blurred_s3_key)
                if job.manifest_s3_key:
                    keys_to_delete.append(job.manifest_s3_key)
                if job.mask_s3_keys:
                    keys_to_delete.extend(v for v in job.mask_s3_keys.values() if v)
                for key in keys_to_delete:
                    try:
                        s3.delete(key)
                    except Exception:
                        logger.exception(
                            "blur_s3_delete_failed",
                            job_id=str(job_id), s3_key=key,
                        )
            except Exception:
                logger.exception("blur_s3_client_failed", job_id=str(job_id))

        await self.repository.session.delete(job)
        await self.repository.session.flush()
