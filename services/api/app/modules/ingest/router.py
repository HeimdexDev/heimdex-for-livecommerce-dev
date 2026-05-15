"""
Agent scene ingestion router.

POST /api/ingest/scenes — receives scene detection results from the Heimdex agent
and indexes them into the scenes OpenSearch index.

Auth: Pre-shared API key (Bearer token) — no user JWT required.
Tenancy: org_id derived from Host header via TenancyMiddleware.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.config import get_settings
from app.dependencies import get_scene_ingest_service
from app.logging_config import get_logger
from app.modules.ingest.auth import verify_agent_token
from app.modules.ingest.rate_limit import require_ingest_rate_limit
from app.modules.ingest.replay import verify_ingest_replay
from app.modules.ingest.schemas import IngestScenesRequest, IngestScenesResponse
from app.modules.ingest.service import SceneIngestService
from app.modules.tenancy.context import OrgContext

logger = get_logger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("/scenes", response_model=IngestScenesResponse)
async def ingest_scenes(
    request: IngestScenesRequest,
    http_request: Request,
    org_ctx: OrgContext = Depends(verify_agent_token),
    _rate_limit: None = Depends(require_ingest_rate_limit),
    _replay: None = Depends(verify_ingest_replay),
    ingest_service: SceneIngestService = Depends(get_scene_ingest_service),
):
    """
    Ingest scene detection results from the Heimdex agent.

    The agent sends a list of scene documents for a single video.
    The SaaS normalizes transcripts, generates embeddings, and indexes
    into the scenes OpenSearch index.

    Auth: Bearer token (pre-shared agent API key).
    Tenancy: org_id from Host header.

    Returns:
        IngestScenesResponse with indexed_count and video_id.

    Raises:
        400: If scenes list exceeds max_scenes limit.
        401: If Bearer token is invalid.
        403: If ingestion is disabled.
        422: If library_id does not belong to the org.
    """
    # Log correlation headers from agent (if present)
    agent_request_id = http_request.headers.get("x-heimdex-request-id", "")
    agent_device_id = http_request.headers.get("x-heimdex-device-id", "")
    if agent_request_id or agent_device_id:
        logger.info(
            "agent_correlation",
            agent_request_id=agent_request_id,
            agent_device_id=agent_device_id,
            org_slug=org_ctx.org_slug,
            video_id=request.video_id,
        )

    settings = get_settings()

    # DoS protection: cap max scenes per request
    if len(request.scenes) > settings.agent_ingest_max_scenes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Too many scenes: {len(request.scenes)} exceeds "
                f"maximum of {settings.agent_ingest_max_scenes} per request"
            ),
        )

    try:
        result = await ingest_service.ingest_scenes(
            request=request,
            org_id=org_ctx.org_id,
        )
    except ValueError as e:
        # Library validation failure
        logger.warning(
            "scene_ingest_validation_error",
            org_id=str(org_ctx.org_id),
            video_id=request.video_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )

    return IngestScenesResponse(**result)
