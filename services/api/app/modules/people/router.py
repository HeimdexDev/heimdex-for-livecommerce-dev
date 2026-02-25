from pathlib import Path as FilePath
from typing import cast
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.dependencies import (
    get_db_session,
    get_people_cluster_label_repository,
    get_people_exclude_preference_repository,
    get_scene_opensearch_client,
)
from app.logging_config import get_logger
from app.modules.auth import get_current_user
from app.modules.people.repository import (
    PeopleClusterLabelRepository,
    PeopleExcludePreferenceRepository,
)
from app.modules.people.schemas import (
    ExcludePreferencesResponse,
    PeopleListResponse,
    PersonResponse,
    PersonVideoItem,
    PersonVideosResponse,
    RenamePersonRequest,
    RenamePersonResponse,
    SetExcludePreferencesRequest,
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
    exclude_repo: PeopleExcludePreferenceRepository = Depends(get_people_exclude_preference_repository),
    scene_opensearch: SceneSearchClient = Depends(get_scene_opensearch_client),
):
    settings = get_settings()
    if not settings.people_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="People feature is not enabled",
        )

    user_id = cast(UUID, user.id)
    logger.debug("list_people_request", user_id=str(user_id), org_id=str(org_ctx.org_id))

    labels = await people_repo.list_by_org(org_ctx.org_id)
    label_map = {entry.person_cluster_id: entry.label for entry in labels}

    excluded_ids = set(await exclude_repo.list_by_user(org_ctx.org_id, user_id))

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
                is_excluded=cluster_id in excluded_ids,
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
                is_excluded=cluster_id in excluded_ids,
            )
        )

    all_cluster_ids = [p.person_cluster_id for p in people]
    rep_scenes = await scene_opensearch.get_representative_scenes_for_people(
        str(org_ctx.org_id), all_cluster_ids
    )
    for person in people:
        scene_info = rep_scenes.get(person.person_cluster_id)
        if scene_info:
            person.representative_video_id = scene_info["video_id"]
            person.representative_scene_id = scene_info["scene_id"]

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


@router.delete("/{person_cluster_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_person(
    person_cluster_id: str,
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    people_repo: PeopleClusterLabelRepository = Depends(get_people_cluster_label_repository),
    exclude_repo: PeopleExcludePreferenceRepository = Depends(get_people_exclude_preference_repository),
    scene_opensearch: SceneSearchClient = Depends(get_scene_opensearch_client),
    db: AsyncSession = Depends(get_db_session),
):
    """Permanently delete a face profile and remove from all scene data."""
    settings = get_settings()
    if not settings.people_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="People feature is not enabled",
        )

    org_id_str = str(org_ctx.org_id)
    logger.info(
        "delete_person_request",
        user_id=str(user.id),
        org_id=org_id_str,
        person_cluster_id=person_cluster_id,
    )

    # 1. Delete cluster label from Postgres (also validates existence)
    deleted_label = await people_repo.delete_by_cluster_id(
        org_ctx.org_id, person_cluster_id
    )

    # 2. Delete all exclude preferences for this cluster (all users)
    exclude_count = await exclude_repo.delete_by_cluster_id(
        org_ctx.org_id, person_cluster_id
    )

    await db.commit()

    # 3. Remove cluster_id from OpenSearch scene documents
    scenes_updated = 0
    try:
        scenes_updated = await scene_opensearch.remove_person_cluster_id(
            org_id_str, person_cluster_id
        )
    except Exception:
        logger.exception(
            "delete_person_opensearch_cleanup_failed",
            org_id=org_id_str,
            person_cluster_id=person_cluster_id,
        )

    # 4. Delete face thumbnail file
    try:
        thumbnail_dir = FilePath(settings.thumbnail_storage_dir)
        face_path = thumbnail_dir / org_id_str / "faces" / f"{person_cluster_id}.jpg"
        if face_path.exists():
            face_path.unlink()
    except Exception:
        logger.exception(
            "delete_person_thumbnail_cleanup_failed",
            org_id=org_id_str,
            person_cluster_id=person_cluster_id,
        )

    if not deleted_label and scenes_updated == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Person cluster not found",
        )

    logger.info(
        "delete_person_complete",
        org_id=org_id_str,
        person_cluster_id=person_cluster_id,
        label_deleted=deleted_label,
        exclude_prefs_deleted=exclude_count,
        scenes_updated=scenes_updated,
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


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


@router.get("/exclude-preferences", response_model=ExcludePreferencesResponse)
async def get_exclude_preferences(
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    exclude_repo: PeopleExcludePreferenceRepository = Depends(get_people_exclude_preference_repository),
):
    settings = get_settings()
    if not settings.people_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="People feature is not enabled",
        )

    user_id = cast(UUID, user.id)
    excluded = await exclude_repo.list_by_user(org_ctx.org_id, user_id)
    return ExcludePreferencesResponse(excluded_person_cluster_ids=excluded)


@router.put("/exclude-preferences", response_model=ExcludePreferencesResponse)
async def set_exclude_preferences(
    request: SetExcludePreferencesRequest,
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    exclude_repo: PeopleExcludePreferenceRepository = Depends(get_people_exclude_preference_repository),
    db: AsyncSession = Depends(get_db_session),
):
    settings = get_settings()
    if not settings.people_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="People feature is not enabled",
        )

    user_id = cast(UUID, user.id)
    logger.debug(
        "set_exclude_preferences",
        user_id=str(user_id),
        org_id=str(org_ctx.org_id),
        count=len(request.person_cluster_ids),
    )

    excluded = await exclude_repo.replace_all(
        org_ctx.org_id, user_id, request.person_cluster_ids
    )
    await db.commit()
    return ExcludePreferencesResponse(excluded_person_cluster_ids=excluded)
