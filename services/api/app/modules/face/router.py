from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db_session, get_face_repository, verify_internal_token as _verify_internal_token
from app.logging_config import get_logger
from app.modules.face.repository import FaceRepository
from app.modules.face.schemas import (
    ExemplarIdMapping,
    FaceIdentityUpsertRequest,
    FaceIdentityUpsertResponse,
    FaceMatchRequest,
    FaceMatchResponse,
    FaceMatchResult,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/internal/face", tags=["internal-face"])


@router.post("/match", response_model=FaceMatchResponse)
async def internal_face_match(
    request: FaceMatchRequest,
    x_heimdex_org_id: str = Header(..., alias="X-Heimdex-Org-Id"),
    _token: str = Depends(_verify_internal_token),
    repository: FaceRepository = Depends(get_face_repository),
):
    try:
        org_id = UUID(x_heimdex_org_id)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid X-Heimdex-Org-Id: {x_heimdex_org_id!r}",
        )

    if request.org_id != str(org_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request org_id does not match X-Heimdex-Org-Id",
        )

    matches = await repository.match_embeddings(
        org_id=org_id,
        embeddings=request.embeddings,
        threshold=request.threshold,
    )

    logger.info(
        "internal_face_match_complete",
        org_id=str(org_id),
        embedding_count=len(request.embeddings),
        matched_count=sum(1 for item in matches if item is not None),
    )

    response_matches: list[FaceMatchResult] = []
    for item in matches:
        if item is None:
            response_matches.append(FaceMatchResult(cluster_id=None, similarity=None))
            continue
        response_matches.append(
            FaceMatchResult(
                cluster_id=item["cluster_id"],
                similarity=item["similarity"],
            )
        )

    return FaceMatchResponse(matches=response_matches)


@router.post("/identities", response_model=FaceIdentityUpsertResponse)
async def internal_face_identities(
    request: FaceIdentityUpsertRequest,
    x_heimdex_org_id: str = Header(..., alias="X-Heimdex-Org-Id"),
    _token: str = Depends(_verify_internal_token),
    repository: FaceRepository = Depends(get_face_repository),
):
    try:
        org_id = UUID(x_heimdex_org_id)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid X-Heimdex-Org-Id: {x_heimdex_org_id!r}",
        )

    if request.org_id != str(org_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request org_id does not match X-Heimdex-Org-Id",
        )
    created = 0
    updated = 0
    exemplar_mappings: list[ExemplarIdMapping] = []

    for item in request.identities:
        is_new, identity_id = await repository.upsert_identity(
            org_id=org_id,
            cluster_id=item.cluster_id,
            embedding=item.embedding,
            quality=item.quality,
            best_thumbnail_video_id=item.video_id,
        )
        exemplar_id = await repository.add_exemplar(
            identity_id=identity_id,
            org_id=org_id,
            video_id=item.video_id,
            scene_id=item.scene_id,
            embedding=item.embedding,
            quality=item.quality,
            bbox_json=item.bbox_json,
        )
        exemplar_mappings.append(
            ExemplarIdMapping(cluster_id=item.cluster_id, exemplar_id=str(exemplar_id))
        )
        if is_new:
            created += 1
        else:
            updated += 1

    logger.info(
        "internal_face_identities_upsert_complete",
        org_id=str(org_id),
        requested=len(request.identities),
        created=created,
        updated=updated,
    )

    return FaceIdentityUpsertResponse(
        created=created, updated=updated, exemplar_ids=exemplar_mappings,
    )
