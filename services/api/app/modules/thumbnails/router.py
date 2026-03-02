import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse

from app.logging_config import get_logger

from app.config import get_settings
from app.modules.ingest.auth import verify_agent_token
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org

logger = get_logger(__name__)

upload_router = APIRouter(prefix="/ingest/thumbnails", tags=["ingest"])
public_router = APIRouter(prefix="/thumbnails", tags=["thumbnails"])

_UNSAFE_PATH_RE = re.compile(r"[/\\\x00]")


def _validate_path_component(value: str, name: str) -> None:
    if not value or _UNSAFE_PATH_RE.search(value) or ".." in value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {name}",
        )


def _validate_resolved_path(constructed: Path, root: Path) -> None:
    resolved = constructed.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid path",
        )


@upload_router.post("/face/{person_cluster_id}")
async def upload_face_thumbnail(
    person_cluster_id: str,
    file: Annotated[UploadFile, File(...)],
    org_ctx: Annotated[OrgContext, Depends(verify_agent_token)],
):
    _validate_path_component(person_cluster_id, "person_cluster_id")

    content_type = (file.content_type or "").lower()
    if content_type not in {"image/jpeg", "image/jpg"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="file must be image/jpeg",
        )

    settings = get_settings()
    root = Path(settings.thumbnail_storage_dir)
    target_dir = root / str(org_ctx.org_id) / "faces"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{person_cluster_id}.jpg"
    _validate_resolved_path(target_path, root)
    data = await file.read()
    target_path.write_bytes(data)

    return {"stored": True, "path": f"faces/{person_cluster_id}"}


@upload_router.post("/{video_id}")
async def ingest_thumbnail(
    video_id: str,
    file: Annotated[UploadFile, File(...)],
    org_ctx: Annotated[OrgContext, Depends(verify_agent_token)],
    scene_id_form: Annotated[str | None, Form(alias="scene_id")] = None,
    scene_id_query: Annotated[str | None, Query(alias="scene_id")] = None,
):
    _validate_path_component(video_id, "video_id")

    scene_id = scene_id_form or scene_id_query
    if not scene_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="scene_id is required",
        )
    _validate_path_component(scene_id, "scene_id")

    content_type = (file.content_type or "").lower()
    if content_type not in {"image/jpeg", "image/jpg"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="file must be image/jpeg",
        )

    settings = get_settings()
    root = Path(settings.thumbnail_storage_dir)
    target_dir = root / str(org_ctx.org_id) / video_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{scene_id}.jpg"
    _validate_resolved_path(target_path, root)
    data = await file.read()
    target_path.write_bytes(data)

    return {"stored": True, "path": f"{video_id}/{scene_id}"}


@public_router.get("/faces/{person_cluster_id}")
async def get_face_thumbnail(
    person_cluster_id: str,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
):
    _validate_path_component(person_cluster_id, "person_cluster_id")

    settings = get_settings()
    root = Path(settings.thumbnail_storage_dir)
    thumbnail_path = root / str(org_ctx.org_id) / "faces" / f"{person_cluster_id}.jpg"
    _validate_resolved_path(thumbnail_path, root)
    if not thumbnail_path.exists():
        logger.warning(
            "face_thumbnail_missing",
            org_id=str(org_ctx.org_id),
            person_cluster_id=person_cluster_id,
            expected_path=str(thumbnail_path),
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thumbnail not found")

    return FileResponse(
        path=thumbnail_path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@public_router.get("/{video_id}/{scene_id}")
async def get_thumbnail(
    video_id: str,
    scene_id: str,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
):
    _validate_path_component(video_id, "video_id")
    _validate_path_component(scene_id, "scene_id")

    settings = get_settings()
    root = Path(settings.thumbnail_storage_dir)
    thumbnail_path = root / str(org_ctx.org_id) / video_id / f"{scene_id}.jpg"
    _validate_resolved_path(thumbnail_path, root)
    if thumbnail_path.exists():
        return FileResponse(
            path=thumbnail_path,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    if video_id.startswith("gd_") and settings.drive_connector_enabled:
        return _get_s3_thumbnail(str(org_ctx.org_id), video_id, scene_id)

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thumbnail not found")


def _get_s3_thumbnail(org_id: str, video_id: str, scene_id: str):
    from fastapi.responses import Response

    from app.config import get_settings as _get_settings
    from app.modules.drive.keys import thumbnail_s3_key
    from app.storage.s3 import S3Client

    s3 = S3Client(bucket=_get_settings().drive_s3_bucket)
    data = s3.get_object_bytes(thumbnail_s3_key(org_id, video_id, scene_id))
    if data:
        return Response(
            content=data,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"},
        )
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thumbnail not found")
