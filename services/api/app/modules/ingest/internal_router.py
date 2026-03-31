"""
Internal ingestion router for drive-workers.

POST /internal/ingest/scenes — scene data from drive-worker
POST /internal/ingest/enrich — enrichment merge from GPU workers
POST /internal/ingest/thumbnails/face/{id} — face thumbnails from face-worker

Auth: Pre-shared internal API key (Bearer token).
Tenancy: org_id passed explicitly via X-Heimdex-Org-Id header (no Host-based
         resolution — workers are internal services, not tenants).
Feature-gated: only registered when DRIVE_CONNECTOR_ENABLED=true.
"""
import re
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
from heimdex_media_contracts.ingest import IngestScenesRequest

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.dependencies import get_db_session, get_org_repository, get_scene_ingest_service
from app.logging_config import get_logger
from app.modules.ingest.schemas import (
    EnrichScenesRequest,
    EnrichScenesResponse,
    IngestScenesResponse,
)
from app.modules.ingest.service import SceneIngestService
from app.modules.orgs.repository import OrgRepository

logger = get_logger(__name__)

router = APIRouter(prefix="/internal/ingest", tags=["internal-ingest"])


from app.dependencies import verify_internal_token as _verify_internal_token


@router.post("/scenes", response_model=IngestScenesResponse)
async def internal_ingest_scenes(
    request: IngestScenesRequest,
    x_heimdex_org_id: str = Header(..., alias="X-Heimdex-Org-Id"),
    _token: str = Depends(_verify_internal_token),
    db: AsyncSession = Depends(get_db_session),
    org_repo: OrgRepository = Depends(get_org_repository),
    ingest_service: SceneIngestService = Depends(get_scene_ingest_service),
):
    """Ingest scenes from drive-worker. Auth: internal API key. Tenancy: X-Heimdex-Org-Id header."""
    try:
        org_id = UUID(x_heimdex_org_id)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid X-Heimdex-Org-Id: {x_heimdex_org_id!r}",
        )

    org = await org_repo.get_by_id(org_id)
    if org is None:
        logger.warning("internal_ingest_unknown_org", org_id=str(org_id))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    settings = get_settings()

    # DoS protection: cap max scenes per request (same limit as agent endpoint)
    if len(request.scenes) > settings.agent_ingest_max_scenes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Too many scenes: {len(request.scenes)} exceeds "
                f"maximum of {settings.agent_ingest_max_scenes} per request"
            ),
        )

    logger.info(
        "internal_ingest_started",
        org_id=str(org_id),
        video_id=request.video_id,
        library_id=str(request.library_id),
        scene_count=len(request.scenes),
    )

    try:
        result = await ingest_service.ingest_scenes(
            request=request,
            org_id=org_id,
        )
    except ValueError as e:
        logger.warning(
            "internal_ingest_validation_error",
            org_id=str(org_id),
            video_id=request.video_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )

    return IngestScenesResponse(**result)


@router.post("/enrich", response_model=EnrichScenesResponse)
async def internal_enrich_scenes(
    request: EnrichScenesRequest,
    x_heimdex_org_id: str = Header(..., alias="X-Heimdex-Org-Id"),
    _token: str = Depends(_verify_internal_token),
    db: AsyncSession = Depends(get_db_session),
    org_repo: OrgRepository = Depends(get_org_repository),
    ingest_service: SceneIngestService = Depends(get_scene_ingest_service),
):
    try:
        org_id = UUID(x_heimdex_org_id)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid X-Heimdex-Org-Id: {x_heimdex_org_id!r}",
        )

    org = await org_repo.get_by_id(org_id)
    if org is None:
        logger.warning("internal_enrich_unknown_org", org_id=str(org_id))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    settings = get_settings()
    if len(request.scenes) > settings.agent_ingest_max_scenes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Too many scenes: {len(request.scenes)} exceeds "
                f"maximum of {settings.agent_ingest_max_scenes} per request"
            ),
        )

    logger.info(
        "internal_enrich_started",
        org_id=str(org_id),
        video_id=request.video_id,
        scene_count=len(request.scenes),
    )

    result = await ingest_service.enrich_scenes(
        request=request,
        org_id=org_id,
    )

    return EnrichScenesResponse(**result)


@router.post("/thumbnails/face/{person_cluster_id}")
async def internal_upload_face_thumbnail(
    person_cluster_id: str,
    file: Annotated[UploadFile, File(...)],
    x_heimdex_org_id: str = Header(..., alias="X-Heimdex-Org-Id"),
    _token: str = Depends(_verify_internal_token),
):
    """Upload face thumbnail from face-worker. Auth: internal API key."""
    _UNSAFE_PATH_RE = re.compile(r"[/\\\x00]")
    if not person_cluster_id or _UNSAFE_PATH_RE.search(person_cluster_id) or ".." in person_cluster_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid person_cluster_id",
        )

    try:
        org_id = UUID(x_heimdex_org_id)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid X-Heimdex-Org-Id: {x_heimdex_org_id!r}",
        )

    content_type = (file.content_type or "").lower()
    if content_type not in {"image/jpeg", "image/jpg"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="file must be image/jpeg",
        )

    settings = get_settings()
    root = Path(settings.thumbnail_storage_dir)
    target_dir = root / str(org_id) / "faces"
    target_path = target_dir / f"{person_cluster_id}.jpg"

    # Validate no path traversal
    resolved = target_path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid path",
        )

    # Override protection: skip if user has selected a custom thumbnail
    from app.modules.face.repository import FaceRepository
    from app.db.base import get_async_session_factory

    factory = get_async_session_factory()
    async with factory() as session:
        repo = FaceRepository(session)
        thumb_source = await repo.get_thumbnail_source(org_id, person_cluster_id)
        if thumb_source and thumb_source != "auto":
            logger.info(
                "internal_face_thumbnail_skipped_user_override",
                org_id=str(org_id),
                person_cluster_id=person_cluster_id,
                thumbnail_source=thumb_source,
            )
            return {"stored": False, "skipped": "user_override"}

    data = await file.read()
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(data)
    except OSError as e:
        logger.error(
            "internal_face_thumbnail_write_failed",
            path=str(target_path),
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store face thumbnail",
        )

    logger.info(
        "internal_face_thumbnail_uploaded",
        org_id=str(org_id),
        person_cluster_id=person_cluster_id,
        size_bytes=len(data),
    )

    return {"stored": True, "path": f"faces/{person_cluster_id}"}
