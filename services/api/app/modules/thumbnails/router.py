from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse

from app.config import get_settings
from app.modules.ingest.auth import verify_agent_token
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org

upload_router = APIRouter(prefix="/ingest/thumbnails", tags=["ingest"])
public_router = APIRouter(prefix="/thumbnails", tags=["thumbnails"])


@upload_router.post("/face/{person_cluster_id}")
async def upload_face_thumbnail(
    person_cluster_id: str,
    file: Annotated[UploadFile, File(...)],
    org_ctx: Annotated[OrgContext, Depends(verify_agent_token)],
):
    content_type = (file.content_type or "").lower()
    if content_type not in {"image/jpeg", "image/jpg"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="file must be image/jpeg",
        )

    settings = get_settings()
    target_dir = Path(settings.thumbnail_storage_dir) / str(org_ctx.org_id) / "faces"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{person_cluster_id}.jpg"
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
    scene_id = scene_id_form or scene_id_query
    if not scene_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="scene_id is required",
        )

    content_type = (file.content_type or "").lower()
    if content_type not in {"image/jpeg", "image/jpg"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="file must be image/jpeg",
        )

    settings = get_settings()
    target_dir = Path(settings.thumbnail_storage_dir) / str(org_ctx.org_id) / video_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{scene_id}.jpg"
    data = await file.read()
    target_path.write_bytes(data)

    return {"stored": True, "path": f"{video_id}/{scene_id}"}


@public_router.get("/faces/{person_cluster_id}")
async def get_face_thumbnail(
    person_cluster_id: str,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
):
    settings = get_settings()
    thumbnail_path = Path(settings.thumbnail_storage_dir) / str(org_ctx.org_id) / "faces" / f"{person_cluster_id}.jpg"
    if not thumbnail_path.exists():
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
    settings = get_settings()
    thumbnail_path = Path(settings.thumbnail_storage_dir) / str(org_ctx.org_id) / video_id / f"{scene_id}.jpg"
    if not thumbnail_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thumbnail not found")

    return FileResponse(
        path=thumbnail_path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )
