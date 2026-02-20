import logging
import re
import unicodedata
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db_session
from app.modules.drive.repository import DriveFileRepository
from app.modules.export.edl import EdlClip, generate_edl
from app.modules.export.schemas import ExportEdlRequest, ExportEdlResponse
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/export", tags=["export"])


def _sanitize_filename(name: str, max_len: int = 120) -> str:
    cleaned = "".join(c for c in name if not unicodedata.category(c).startswith("C"))
    cleaned = re.sub(r"[^\w\s\-_.,()]", "_", cleaned)
    cleaned = cleaned.strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len]
    return cleaned or "heimdex_export"


@router.post("/edl")
async def export_edl(
    body: ExportEdlRequest,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    file_repo = DriveFileRepository(db)

    resolved_clips: list[EdlClip] = []
    unresolved_clips: list[str] = []

    for clip in body.clips:
        if not clip.video_id.startswith("gd_"):
            unresolved_clips.append(clip.video_id)
            continue

        drive_file = await file_repo.get_by_video_id(org_ctx.org_id, clip.video_id)
        if drive_file is None:
            unresolved_clips.append(clip.video_id)
            continue

        if clip.start_ms >= clip.end_ms:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"start_ms must be less than end_ms for clip {clip.video_id}",
            )

        clip_name = clip.clip_name.strip() or drive_file.file_name
        media_path = drive_file.file_name
        source_path: str | None = None
        if drive_file.drive_path:
            source_path = (
                f"{drive_file.drive_path}/{drive_file.file_name}"
                if not drive_file.drive_path.endswith("/")
                else f"{drive_file.drive_path}{drive_file.file_name}"
            )

        clip_payload: EdlClip = {
            "clip_name": clip_name,
            "media_path": media_path,
            "start_ms": clip.start_ms,
            "end_ms": clip.end_ms,
        }
        if source_path is not None:
            clip_payload["source_path"] = source_path

        resolved_clips.append(clip_payload)

    if not resolved_clips:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No clips could be resolved. Ensure all video_ids start with 'gd_' and exist.",
        )

    project_name = _sanitize_filename(body.project_name)
    edl_content = generate_edl(resolved_clips, project_name, body.frame_rate)
    filename = f"{project_name}.edl"

    logger.info(
        "edl_exported",
        extra={
            "org_id": str(org_ctx.org_id),
            "project_name": project_name,
            "clip_count": len(resolved_clips),
            "unresolved": len(unresolved_clips),
        },
    )

    _response_meta = ExportEdlResponse(
        clip_count=len(resolved_clips),
        unresolved_clips=unresolved_clips,
        filename=filename,
    )

    return Response(
        content=edl_content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{_response_meta.filename}"',
            "X-Clip-Count": str(_response_meta.clip_count),
            "X-Unresolved-Clips": ",".join(_response_meta.unresolved_clips)
            if _response_meta.unresolved_clips
            else "",
        },
    )
