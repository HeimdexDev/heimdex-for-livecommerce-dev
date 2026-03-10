import asyncio
import logging
import os
import re
import shutil
import tempfile
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db_session
from app.dependencies import get_drive_file_repository, get_export_record_repository
from app.modules.drive.repository import DriveFileRepository
from app.modules.export.edl import EdlClip, generate_edl
from app.modules.export.fcp_xml import FcpClip, generate_fcp_xml
from app.modules.export.fcpxml_writer import (
    ClipMarker,
    FCPXMLClip,
    FCPXMLWriteOptions,
    TranscriptMarker,
    generate_fcpxml as generate_fcpxml_18,
)
from app.modules.export.packager import (
    ExportClipMetadata,
    PackageOptions,
    package_premiere_export,
)
from app.modules.drive.models import DriveConnection, DriveFile
from app.modules.export.schemas import (
    ExportClipRequest,
    ExportEdlRequest,
    ExportEdlResponse,
    ExportPremierePackageRequest,
    ExportPremiereRequest,
    ProxyPackRequest,
    ProxyPackInitResponse,
    ProxyPackStatusResponse,
)
from app.modules.export.hashing import compute_export_hash
from app.modules.export.limits import deduplicate_proxies, estimate_export_size
from app.modules.export.models import ExportRecord
from app.modules.export.repository import ExportRecordRepository
from app.sqs_producer import publish_export_job
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org
from app.config import get_settings
from app.storage.s3 import S3Client
from app.modules.auth.service import get_current_user
from app.modules.users.models import User

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
    file_repo: Annotated[DriveFileRepository, Depends(get_drive_file_repository)],
):
    gd_video_ids = [c.video_id for c in body.clips if c.video_id.startswith("gd_")]
    drive_files_map = await file_repo.get_by_video_ids(org_ctx.org_id, gd_video_ids)

    resolved_clips: list[EdlClip] = []
    unresolved_clips: list[str] = []

    for clip in body.clips:
        if not clip.video_id.startswith("gd_"):
            unresolved_clips.append(clip.video_id)
            continue

        drive_file = drive_files_map.get(clip.video_id)
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
    file_repo: Annotated[DriveFileRepository, Depends(get_drive_file_repository)],
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
        await s3.download_file_async(drive_file.proxy_s3_key, input_path)

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
    file_repo: Annotated[DriveFileRepository, Depends(get_drive_file_repository)],
):
    """Generate FCP 7 XML for Premiere Pro with Google Drive local paths."""
    # Normalize mount path: strip trailing slashes
    mount = body.drive_mount_path.rstrip("/").rstrip("\\")

    gd_video_ids = [c.video_id for c in body.clips if c.video_id.startswith("gd_")]
    drive_files_map = await file_repo.get_by_video_ids(org_ctx.org_id, gd_video_ids)

    resolved_clips: list[FcpClip] = []
    unresolved_clips: list[str] = []

    for clip in body.clips:
        if not clip.video_id.startswith("gd_"):
            unresolved_clips.append(clip.video_id)
            continue

        drive_file = drive_files_map.get(clip.video_id)
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


# --- Premiere Package Export (FCPXML 1.8 + ZIP) ---


_DEFAULT_FPS = 29.97
_DEFAULT_WIDTH = 1920
_DEFAULT_HEIGHT = 1080


@router.post("/premiere-package")
async def export_premiere_package(
    body: ExportPremierePackageRequest,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    file_repo: Annotated[DriveFileRepository, Depends(get_drive_file_repository)],
):
    """Generate a Premiere Pro export package (ZIP) with FCPXML 1.8 timeline.

    The package contains:
    - {sequence_name}.fcpxml — FCPXML 1.8 timeline referencing Google Drive media
    - manifest.json — canonical mapping with export metadata
    - README.txt — import instructions (Korean + English)
    - scenes.csv — spreadsheet for editors

    Clips reference original media via file:// URLs resolved from the user's
    Google Drive mount path + DriveConnection metadata. No agent required.
    """

    # Normalize mount path
    mount = body.drive_mount_path.rstrip("/").rstrip("\\")

    # Collect unique video_ids and fetch DriveFile records in one query
    video_ids = list({clip.video_id for clip in body.clips})
    non_gd = [v for v in video_ids if not v.startswith("gd_")]
    if non_gd:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"video_id must start with 'gd_': {non_gd[0]}",
        )

    drive_files_by_video_id = await file_repo.get_by_video_ids(org_ctx.org_id, video_ids)
    missing = [v for v in video_ids if v not in drive_files_by_video_id]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video not found: {missing[0]}",
        )

    connections_by_id: dict[object, DriveConnection] = {}
    for df in drive_files_by_video_id.values():
        if df.connection_id not in connections_by_id:
            conn = await db.get(DriveConnection, df.connection_id)
            if conn:
                connections_by_id[df.connection_id] = conn

    # Build FCPXML clips and export metadata
    fcpxml_clips: list[FCPXMLClip] = []
    export_clip_metas: list[ExportClipMetadata] = []

    for clip_input in body.clips:
        df = drive_files_by_video_id[clip_input.video_id]

        # Validate in/out
        if clip_input.start_ms >= clip_input.end_ms:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"start_ms ({clip_input.start_ms}) must be less than "
                    f"end_ms ({clip_input.end_ms}) for scene {clip_input.scene_id}"
                ),
            )

        # Resolve local Google Drive path
        conn = connections_by_id.get(df.connection_id)
        local_path = _resolve_drive_path(mount, conn, df)

        # Get video metadata (fallback for pre-backfill videos)
        fps = df.video_fps or _DEFAULT_FPS
        width = df.video_width or _DEFAULT_WIDTH
        height = df.video_height or _DEFAULT_HEIGHT


        # Build markers
        clip_markers: tuple[ClipMarker, ...] = ()
        transcript_markers: tuple[TranscriptMarker, ...] = ()

        if body.include_markers:
            note_parts: list[str] = []
            if clip_input.label:
                note_parts.append(clip_input.label)
            elif clip_input.video_title:
                note_parts.append(clip_input.video_title)
            if clip_input.keyword_tags:
                note_parts.append("Tags: " + ", ".join(clip_input.keyword_tags))
            if note_parts:
                clip_markers = (
                    ClipMarker(
                        start_ms=clip_input.start_ms,
                        end_ms=clip_input.end_ms,
                        note=" | ".join(note_parts),
                    ),
                )

        if body.include_transcript_markers and clip_input.transcript_raw:
            transcript_markers = (
                TranscriptMarker(
                    start_ms=clip_input.start_ms,
                    end_ms=clip_input.end_ms,
                    text=clip_input.transcript_raw[:200],
                ),
            )

        fcpxml_clips.append(FCPXMLClip(
            clip_name=clip_input.label or clip_input.video_title or df.file_name,
            file_path=local_path,
            start_ms=clip_input.start_ms,
            end_ms=clip_input.end_ms,
            fps=fps,
            width=width,
            height=height,
            markers=clip_markers,
            transcript_markers=transcript_markers,
        ))

        # Build export metadata for manifest/CSV
        relative_path = _relative_drive_path(conn, df)
        export_clip_metas.append(ExportClipMetadata(
            scene_id=clip_input.scene_id,
            video_id=clip_input.video_id,
            video_title=clip_input.video_title or df.file_name,
            source_file=df.file_name,
            source_path=relative_path,
            google_drive_link=df.web_view_link or "",
            edit_in_ms=clip_input.start_ms,
            edit_out_ms=clip_input.end_ms,
            fps=fps,
            width=width,
            height=height,
            keyword_tags=clip_input.keyword_tags,
            transcript_raw=clip_input.transcript_raw,
            label=clip_input.label,
        ))

    # Generate FCPXML
    fcpxml_options = FCPXMLWriteOptions(
        gap_ms=body.clip_gap_ms,
        include_markers=body.include_markers,
        include_transcript_markers=body.include_transcript_markers,
    )
    fcpxml_content = generate_fcpxml_18(fcpxml_clips, body.sequence_name, fcpxml_options)

    # Package into ZIP
    pkg_options = PackageOptions(
        sequence_name=body.sequence_name,
        drive_mount_path=mount,
        clip_gap_ms=body.clip_gap_ms,
        include_markers=body.include_markers,
        include_transcript_markers=body.include_transcript_markers,
    )
    zip_bytes = package_premiere_export(fcpxml_content, export_clip_metas, pkg_options)

    safe_name = _sanitize_filename(body.sequence_name)
    filename = f"{safe_name}_premiere.zip"

    logger.info(
        "premiere_package_exported",
        extra={
            "org_id": str(org_ctx.org_id),
            "sequence_name": body.sequence_name,
            "clip_count": len(body.clips),
            "zip_size_bytes": len(zip_bytes),
            "format": "fcpxml_1.8",
        },
    )

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": _content_disposition(filename),
            "X-Clip-Count": str(len(body.clips)),
        },
    )


def _resolve_drive_path(mount: str, conn: DriveConnection | None, df: DriveFile) -> str:
    """Resolve a DriveFile to an absolute local path under the Google Drive mount.

    Reuses the same logic as the existing /premiere endpoint (lines 312-330)
    but decoupled into a standalone function.
    """
    if conn is None:
        return f"{mount}/{df.drive_path or df.file_name}"

    if conn.scope_type == "drive" and conn.drive_name:
        return f"{mount}/Shared drives/{conn.drive_name}/{df.drive_path}"
    elif conn.scope_type == "folder" and conn.folder_path:
        return f"{mount}/{conn.folder_path}/{df.drive_path}"
    else:
        return f"{mount}/{df.drive_path or df.file_name}"


def _relative_drive_path(conn: DriveConnection | None, df: DriveFile) -> str:
    """Build the relative path within Google Drive (for manifest.json)."""
    if conn is None:
        return df.drive_path or df.file_name

    if conn.scope_type == "drive" and conn.drive_name:
        return f"Shared drives/{conn.drive_name}/{df.drive_path}"
    elif conn.scope_type == "folder" and conn.folder_path:
        return f"{conn.folder_path}/{df.drive_path}"
    else:
        return df.drive_path or df.file_name


# --- Proxy Pack Export (async via SQS) ---


@router.post("/proxy-pack", response_model=ProxyPackInitResponse)
async def initiate_proxy_pack(
    body: ProxyPackRequest,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    file_repo: Annotated[DriveFileRepository, Depends(get_drive_file_repository)],
    export_repo: Annotated[ExportRecordRepository, Depends(get_export_record_repository)],
):
    settings = get_settings()

    if len(body.clips) > settings.export_max_clips:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Clip count ({len(body.clips)}) exceeds limit ({settings.export_max_clips})",
        )

    video_ids = list({clip.video_id for clip in body.clips})
    non_gd = [v for v in video_ids if not v.startswith("gd_")]
    if non_gd:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"video_id must start with 'gd_': {non_gd[0]}",
        )

    drive_files_by_vid = await file_repo.get_by_video_ids(org_ctx.org_id, video_ids)
    missing = [v for v in video_ids if v not in drive_files_by_vid]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video not found: {missing[0]}",
        )
    no_proxy = [v for v, df in drive_files_by_vid.items() if not df.proxy_s3_key]
    if no_proxy:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Proxy not available for video: {no_proxy[0]}",
        )

    clip_dicts = [
        {"scene_id": c.scene_id, "video_id": c.video_id, "start_ms": c.start_ms, "end_ms": c.end_ms}
        for c in body.clips
    ]
    deduped = deduplicate_proxies(clip_dicts, drive_files_by_vid)

    if len(deduped) > settings.export_max_proxies:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Proxy count ({len(deduped)}) exceeds limit ({settings.export_max_proxies})",
        )

    estimate = estimate_export_size(deduplicated_files=deduped, clip_count=len(body.clips))

    if estimate.total_bytes > settings.export_max_size_bytes:
        size_gb = estimate.total_bytes / (1024 ** 3)
        limit_gb = settings.export_max_size_bytes / (1024 ** 3)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Estimated export size ({size_gb:.1f} GB) exceeds limit ({limit_gb:.1f} GB)",
        )

    export_hash = compute_export_hash(
        org_id=str(org_ctx.org_id),
        clips=clip_dicts,
        include_markers=body.include_markers,
        include_transcript_markers=body.include_transcript_markers,
        clip_gap_ms=body.clip_gap_ms,
    )

    cached = await export_repo.find_cached(org_id=org_ctx.org_id, export_hash=export_hash)
    if cached:
        return ProxyPackInitResponse(
            job_id=str(cached.id),
            status="ready",
            estimated_size_bytes=cached.size_bytes or estimate.total_bytes,
            proxy_count=cached.proxy_count,
            clip_count=cached.clip_count,
        )

    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.export_expiry_days)

    request_snapshot = {
        "sequence_name": body.sequence_name,
        "clips": [c.model_dump() for c in body.clips],
        "clip_gap_ms": body.clip_gap_ms,
        "include_markers": body.include_markers,
        "include_transcript_markers": body.include_transcript_markers,
        "proxy_keys": {vid: df.proxy_s3_key for vid, df in drive_files_by_vid.items()},
    }

    record = await export_repo.create(
        org_id=org_ctx.org_id,
        user_id=cast(UUID, user.id),
        export_hash=export_hash,
        clip_count=len(body.clips),
        proxy_count=len(deduped),
        sequence_name=body.sequence_name,
        request_body=request_snapshot,
        expires_at=expires_at,
    )

    publish_export_job(
        export_id=record.id,
        org_id=org_ctx.org_id,
        user_id=cast(UUID, user.id),
        export_hash=export_hash,
    )

    logger.info(
        "proxy_pack_initiated",
        extra={
            "org_id": str(org_ctx.org_id),
            "export_id": str(record.id),
            "export_hash": export_hash,
            "clip_count": len(body.clips),
            "proxy_count": len(deduped),
            "estimated_bytes": estimate.total_bytes,
        },
    )

    return ProxyPackInitResponse(
        job_id=str(record.id),
        status="pending",
        estimated_size_bytes=estimate.total_bytes,
        proxy_count=len(deduped),
        clip_count=len(body.clips),
    )


@router.get("/proxy-pack/{job_id}", response_model=ProxyPackStatusResponse)
async def get_proxy_pack_status(
    job_id: str,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    export_repo: Annotated[ExportRecordRepository, Depends(get_export_record_repository)],
):
    try:
        export_uuid = UUID(job_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid job_id format",
        )

    record = await export_repo.get(export_uuid, org_ctx.org_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Export job not found",
        )

    download_url: str | None = None
    expires_at_str: str | None = None

    if record.status == "ready" and record.s3_key:
        settings = get_settings()
        s3 = S3Client(bucket=settings.drive_s3_bucket)
        download_url = await s3.generate_presigned_url_async(record.s3_key, expires_in=3600)
        expires_at_str = record.expires_at.isoformat()

    return ProxyPackStatusResponse(
        job_id=str(record.id),
        status=record.status,
        download_url=download_url,
        size_bytes=record.size_bytes,
        error=record.error_message,
        expires_at=expires_at_str,
    )
