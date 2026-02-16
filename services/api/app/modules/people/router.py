from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.dependencies import (
    get_db_session,
    get_people_cluster_label_repository,
    get_scene_opensearch_client,
)
from app.logging_config import get_logger
from app.modules.auth import get_current_user
from app.modules.people.repository import PeopleClusterLabelRepository
from app.modules.people.schemas import (
    PeopleListResponse,
    PersonResponse,
    PersonVideoItem,
    PersonVideosResponse,
    RenamePersonRequest,
    RenamePersonResponse,
)
from app.modules.search.scene_client import SceneSearchClient
from app.modules.tenancy import OrgContext, get_current_org
from app.modules.users.models import User

logger = get_logger(__name__)
router = APIRouter(prefix="/people", tags=["people"])


@router.get("", response_model=PeopleListResponse)
async def list_people(
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    people_repo: PeopleClusterLabelRepository = Depends(get_people_cluster_label_repository),
    scene_opensearch: SceneSearchClient = Depends(get_scene_opensearch_client),
):
    settings = get_settings()
    if not settings.people_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="People feature is not enabled",
        )

    logger.debug("list_people_request", user_id=str(user.id), org_id=str(org_ctx.org_id))

    labels = await people_repo.list_by_org(org_ctx.org_id)
    label_map = {entry.person_cluster_id: entry.label for entry in labels}

    facets = await scene_opensearch.get_facets(str(org_ctx.org_id), {})
    people_buckets = facets.get("people", [])

    people: list[PersonResponse] = []
    seen_cluster_ids: set[str] = set()

    for bucket in people_buckets:
        cluster_id = str(bucket.get("key", ""))
        if not cluster_id:
            continue
        seen_cluster_ids.add(cluster_id)
        people.append(
            PersonResponse(
                person_cluster_id=cluster_id,
                label=label_map.get(cluster_id),
                face_count=int(bucket.get("doc_count", 0)),
            )
        )

    for cluster_id, label in sorted(label_map.items()):
        if cluster_id in seen_cluster_ids:
            continue
        people.append(
            PersonResponse(
                person_cluster_id=cluster_id,
                label=label,
                face_count=0,
            )
        )

    return PeopleListResponse(people=people, total=len(people))


@router.patch("/{person_cluster_id}", response_model=RenamePersonResponse)
async def rename_person(
    person_cluster_id: str,
    request: RenamePersonRequest,
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    people_repo: PeopleClusterLabelRepository = Depends(get_people_cluster_label_repository),
    db: AsyncSession = Depends(get_db_session),
):
    settings = get_settings()
    if not settings.people_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="People feature is not enabled",
        )

    logger.debug(
        "rename_person_request",
        user_id=str(user.id),
        org_id=str(org_ctx.org_id),
        person_cluster_id=person_cluster_id,
    )

    existing = await people_repo.get_by_cluster_id(org_ctx.org_id, person_cluster_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Person cluster not found",
        )

    updated = await people_repo.set_label(org_ctx.org_id, person_cluster_id, request.label)
    await db.commit()

    return RenamePersonResponse(
        person_cluster_id=updated.person_cluster_id,
        label=updated.label,
    )


@router.get("/{person_cluster_id}/videos", response_model=PersonVideosResponse)
async def person_videos(
    person_cluster_id: str,
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    scene_opensearch: SceneSearchClient = Depends(get_scene_opensearch_client),
):
    settings = get_settings()
    if not settings.people_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="People feature is not enabled",
        )

    logger.debug(
        "person_videos_request",
        user_id=str(user.id),
        org_id=str(org_ctx.org_id),
        person_cluster_id=person_cluster_id,
    )

    result = await scene_opensearch.get_videos_by_person(
        str(org_ctx.org_id),
        person_cluster_id,
    )

    videos = [
        PersonVideoItem(
            video_id=v["video_id"],
            video_title=v.get("video_title"),
            scene_count=v.get("scene_count", 0),
        )
        for v in result
    ]

    return PersonVideosResponse(
        person_cluster_id=person_cluster_id,
        videos=videos,
        total=len(videos),
    )
