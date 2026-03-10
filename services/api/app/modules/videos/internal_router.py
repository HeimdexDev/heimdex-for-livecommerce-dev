import asyncio
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db_session, get_reprocess_repository, get_scene_opensearch_client
from app.modules.search.scene_client import SceneSearchClient
from app.modules.videos.reprocess_repository import ReprocessRepository
from app.sqs_producer import (
    publish_enrichment_jobs,
    publish_scene_enrichment_jobs,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/videos", tags=["videos-internal"])

from app.dependencies import verify_internal_token as _verify_internal_token


async def _publish_scene_jobs_in_background(
    *,
    file_id: UUID,
    org_id: UUID,
    video_id: str,
    scenes: list[dict[str, Any]],
) -> None:
    """Publish per-scene SQS messages in a background thread.

    Runs ``publish_scene_enrichment_jobs`` via ``run_in_executor`` so the
    synchronous boto3 ``send_message_batch`` calls don't block the event loop.
    Called from ``asyncio.create_task()`` after the PATCH response is sent.
    """
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: publish_scene_enrichment_jobs(
                file_id=file_id,
                org_id=org_id,
                video_id=video_id,
                scenes=scenes,
            ),
        )
        logger.info(
            "reprocess_scene_enrichment_jobs_published",
            extra={"video_id": video_id, "scene_count": len(scenes)},
        )
    except Exception:
        logger.warning(
            "reprocess_scene_enrichment_jobs_failed",
            extra={"video_id": video_id, "scene_count": len(scenes)},
            exc_info=True,
        )


@router.delete("/{video_id}/scenes")
async def delete_video_scenes(
    video_id: str,
    x_heimdex_org_id: str = Header(..., alias="X-Heimdex-Org-Id"),
    _token: str = Depends(_verify_internal_token),
    scene_client: SceneSearchClient = Depends(get_scene_opensearch_client),
):
    try:
        org_id = UUID(x_heimdex_org_id)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid X-Heimdex-Org-Id: {x_heimdex_org_id!r}",
        )

    deleted = await scene_client.delete_scenes_by_video_id(str(org_id), video_id)
    return {"deleted": deleted}


@router.patch("/{video_id}/reprocess/{job_id}/status")
async def update_reprocess_status(
    video_id: str,
    job_id: str,
    status_value: str = Body(..., alias="status"),
    scene_count: int | None = Body(None),
    error: str | None = Body(None),
    org_id: str | None = Body(None),
    keyframe_s3_prefix: str | None = Body(None),
    audio_s3_key: str | None = Body(None),
    _token: str = Depends(_verify_internal_token),
    db: AsyncSession = Depends(get_db_session),
    repo: ReprocessRepository = Depends(get_reprocess_repository),
):
    try:
        parsed_job_id = UUID(job_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid job_id format",
        )

    await repo.update_status(
        parsed_job_id,
        status_value,
        scene_count=scene_count,
        error=error,
    )

    # Publish enrichment SQS jobs when resplit completes successfully.
    # Mirrors the pattern in internal_processing_router.py and
    # youtube/internal_router.py — enrichment fires as a side effect
    # of status transitioning to 'completed'.
    if (
        status_value == "completed"
        and scene_count
        and scene_count > 0
        and org_id
        and keyframe_s3_prefix
    ):
        file_uuid = await _resolve_file_id(db, video_id, UUID(org_id))
        if file_uuid is not None:
            parsed_org_id = UUID(org_id)

            # v1: per-video enrichment for STT, OCR, face
            publish_enrichment_jobs(
                file_id=file_uuid,
                org_id=parsed_org_id,
                video_id=video_id,
                keyframe_s3_prefix=keyframe_s3_prefix,
                audio_s3_key=audio_s3_key,
            )

            # v2: per-scene enrichment for caption + visual-embed
            scenes_for_publish = [
                {
                    "scene_id": f"{video_id}_scene_{i:03d}",
                    "scene_index": i,
                    "keyframe_s3_key": f"{keyframe_s3_prefix}{video_id}_scene_{i:03d}.jpg",
                }
                for i in range(scene_count)
            ]
            asyncio.create_task(
                _publish_scene_jobs_in_background(
                    file_id=file_uuid,
                    org_id=parsed_org_id,
                    video_id=video_id,
                    scenes=scenes_for_publish,
                )
            )

            logger.info(
                "reprocess_enrichment_published",
                extra={
                    "video_id": video_id,
                    "job_id": job_id,
                    "scene_count": scene_count,
                    "file_id": str(file_uuid),
                },
            )

    return {"status": "ok"}


async def _resolve_file_id(
    db: AsyncSession, video_id: str, org_id: UUID,
) -> UUID | None:
    """Look up the real DriveFile or YouTubeVideo UUID for enrichment tracking.

    Enrichment workers use this UUID to report per-file enrichment status.
    Kept as a separate function to avoid coupling the status handler to
    repository internals.
    """
    if video_id.startswith("gd_"):
        from app.modules.drive.repository import DriveFileRepository
        repo = DriveFileRepository(db)
        drive_file = await repo.get_by_video_id(org_id, video_id)
        return drive_file.id if drive_file else None
    elif video_id.startswith("yt_"):
        from app.modules.youtube.repository import YouTubeVideoRepository
        repo = YouTubeVideoRepository(db)
        yt_video = await repo.get_by_video_id(org_id, video_id)
        return yt_video.id if yt_video else None
    return None
