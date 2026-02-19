"""
Internal scene ingestion router for drive-worker.

POST /internal/ingest/scenes — accepts scene data from the drive-worker
over Docker network and delegates to SceneIngestService.

Auth: Pre-shared internal API key (Bearer token).
Tenancy: org_id passed explicitly via X-Heimdex-Org-Id header (no Host-based
         resolution — the drive-worker is an internal service, not a tenant).
Feature-gated: only registered when DRIVE_CONNECTOR_ENABLED=true.
"""
import hmac
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.config import get_settings
from app.dependencies import get_scene_ingest_service
from app.logging_config import get_logger
from app.modules.ingest.schemas import IngestScenesRequest, IngestScenesResponse
from app.modules.ingest.service import SceneIngestService

logger = get_logger(__name__)

router = APIRouter(prefix="/internal/ingest", tags=["internal-ingest"])


async def _verify_internal_token(
    authorization: str = Header(..., alias="Authorization"),
) -> str:
    """Validate internal Bearer token against DRIVE_INTERNAL_API_KEY."""
    settings = get_settings()

    if not settings.drive_internal_api_key:
        logger.error("drive_internal_api_key_not_configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Internal ingest not configured",
        )

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header",
        )

    token = parts[1]
    if not hmac.compare_digest(token, settings.drive_internal_api_key):
        logger.warning("internal_ingest_invalid_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal API key",
        )

    return token


@router.post("/scenes", response_model=IngestScenesResponse)
async def internal_ingest_scenes(
    request: IngestScenesRequest,
    x_heimdex_org_id: str = Header(..., alias="X-Heimdex-Org-Id"),
    _token: str = Depends(_verify_internal_token),
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
