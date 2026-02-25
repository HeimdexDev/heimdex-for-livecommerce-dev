import asyncio
import logging
import os
import re
import shutil
import tempfile
import unicodedata
from pathlib import Path
from urllib.parse import quote
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db_session
from app.modules.drive.repository import DriveFileRepository
from app.modules.export.edl import EdlClip, generate_edl
from app.modules.export.fcp_xml import FcpClip, generate_fcp_xml
from app.modules.drive.models import DriveConnection
from app.modules.export.schemas import ExportClipRequest, ExportEdlRequest, ExportEdlResponse, ExportPremiereRequest
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org
from app.config import get_settings
from app.storage.s3 import S3Client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/export", tags=["export"])


def _sanitize_filename(name: str, max_len: int = 120) -> str:
    cleaned = "".join(c for c in name if not unicodedata.category(c).startswith("C"))
    cleaned = re.sub(r"[^\w\s\-_.,()]", "_", cleaned)
    cleaned = cleaned.strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len]
    return cleaned or "heimdex_export"


_FFMPEG_TIMEOUT_S = 120
_MAX_CLIP_DURATION_MS = 300_000  # 5 minutes


def _content_disposition(raw_filename: str) -> str:
    """RFC 5987 Content-Disposition with ASCII fallback + UTF-8 filename*."""
    ascii_name = raw_filename.encode("ascii", "replace").decode("ascii")
    utf8_name = quote(raw_filename, safe="")
    return (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{utf8_name}"
    )


async def _extract_clip(
    input_path: Path,
    output_path: Path,
    start_ms: int,
    end_ms: int,
) -> None:
    """Extract a video clip using ffmpeg -c copy (no re-encoding)."""
    start_s = start_ms / 1000.0
    duration_s = (end_ms - start_ms) / 1000.0
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start_s:.3f}",
        "-i", str(input_path),
        "-t", f"{duration_s:.3f}",
        "-c", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=_FFMPEG_TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Clip extraction timed out",
        )
    if proc.returncode != 0:
        logger.error(
            "ffmpeg_clip_failed",
            extra={"returncode": proc.returncode, "stderr": stderr.decode(errors="replace")[:500]},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to extract clip",
        )


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

    disposition = _content_disposition(_response_meta.filename)
    return Response(
        content=edl_content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": disposition,
            "X-Clip-Count": str(_response_meta.clip_count),
            "X-Unresolved-Clips": ",".join(_response_meta.unresolved_clips)
            if _response_meta.unresolved_clips
            else "",
        },
    )


@router.post("/clip")
async def export_clip(
    body: ExportClipRequest,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Extract and download a trimmed video clip from a cloud video."""
    if not body.video_id.startswith("gd_"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Clip export is only available for cloud (gd_) videos",
        )

    if body.start_ms >= body.end_ms:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_ms must be less than end_ms",
        )

    if body.end_ms - body.start_ms > _MAX_CLIP_DURATION_MS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Clip duration exceeds maximum of {_MAX_CLIP_DURATION_MS // 1000}s",
        )

    if not shutil.which("ffmpeg"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ffmpeg is not available on this server",
        )

    settings = get_settings()
    file_repo = DriveFileRepository(db)
    drive_file = await file_repo.get_by_video_id(org_ctx.org_id, body.video_id)
    if drive_file is None or not drive_file.proxy_s3_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found or proxy not available",
        )

    s3 = S3Client(bucket=settings.drive_s3_bucket)

    tmp_dir = Path(tempfile.mkdtemp(prefix="heimdex_clip_"))
    try:
        # Download proxy video from S3
        input_path = tmp_dir / "source.mp4"
        s3.download_file(drive_file.proxy_s3_key, input_path)

        # Extract clip with ffmpeg
        output_path = tmp_dir / "clip.mp4"
        await _extract_clip(input_path, output_path, body.start_ms, body.end_ms)

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Clip extraction produced empty output",
            )

        clip_name = body.clip_name.strip() or drive_file.file_name
        safe_name = _sanitize_filename(os.path.splitext(clip_name)[0])
        filename = f"{safe_name}.mp4"

        logger.info(
            "clip_exported",
            extra={
                "org_id": str(org_ctx.org_id),
                "video_id": body.video_id,
                "start_ms": body.start_ms,
                "end_ms": body.end_ms,
                "clip_size": output_path.stat().st_size,
            },
        )

        return FileResponse(
            path=str(output_path),
            media_type="video/mp4",
            filename=filename,
            headers={"Content-Disposition": _content_disposition(filename)},
            background=_cleanup_task(tmp_dir),
        )
    except HTTPException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        logger.exception("clip_export_unexpected_error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error during clip export",
        )


def _cleanup_task(tmp_dir: Path):
    """BackgroundTask that removes the temp directory after response is sent."""
    from starlette.background import BackgroundTask
    return BackgroundTask(shutil.rmtree, tmp_dir, ignore_errors=True)


@router.post("/premiere")
async def export_premiere(
    body: ExportPremiereRequest,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Generate FCP 7 XML for Premiere Pro with Google Drive local paths."""
    file_repo = DriveFileRepository(db)

    # Normalize mount path: strip trailing slashes
    mount = body.drive_mount_path.rstrip("/").rstrip("\\")

    resolved_clips: list[FcpClip] = []
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

        # Resolve local Google Drive path
        conn = await db.get(DriveConnection, drive_file.connection_id)
        if conn is None:
            unresolved_clips.append(clip.video_id)
            continue

        # Build local path based on connection type
        if conn.scope_type == "drive" and conn.drive_name:
            # Shared Drive: {mount}/Shared drives/{drive_name}/{drive_path}
            local_path = f"{mount}/Shared drives/{conn.drive_name}/{drive_file.drive_path}"
        elif conn.scope_type == "folder" and conn.folder_path:
            # My Drive folder: {mount}/{folder_path}/{drive_path}
            folder_base = conn.folder_path
            # folder_path may start with '내 드라이브/' or 'My Drive/'
            # The actual mount maps directly, e.g. mount/My Drive/subfolder/...
            local_path = f"{mount}/{folder_base}/{drive_file.drive_path}"
        else:
            # Fallback: just use drive_path under mount
            local_path = f"{mount}/{drive_file.drive_path}"

        clip_name = clip.clip_name.strip() or drive_file.file_name

        resolved_clips.append(FcpClip(
            clip_name=clip_name,
            file_path=local_path,
            file_name=drive_file.file_name,
            start_ms=clip.start_ms,
            end_ms=clip.end_ms,
            source_duration_ms=drive_file.proxy_duration_ms or 0,
        ))

    if not resolved_clips:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No clips could be resolved. Ensure all video_ids start with 'gd_' and exist.",
        )

    project_name = _sanitize_filename(body.project_name)
    xml_content = generate_fcp_xml(resolved_clips, project_name, body.frame_rate)
    filename = f"{project_name}.xml"

    logger.info(
        "premiere_exported",
        extra={
            "org_id": str(org_ctx.org_id),
            "project_name": project_name,
            "clip_count": len(resolved_clips),
            "unresolved": len(unresolved_clips),
            "format": "fcp_xml",
        },
    )

    return Response(
        content=xml_content,
        media_type="application/xml",
        headers={
            "Content-Disposition": _content_disposition(filename),
            "X-Clip-Count": str(len(resolved_clips)),
            "X-Unresolved-Clips": ",".join(unresolved_clips)
            if unresolved_clips
            else "",
        },
    )
