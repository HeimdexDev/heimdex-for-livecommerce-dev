import logging
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.modules.auth.service import get_current_user
from app.dependencies import (
    get_saved_short_repository,
    get_scene_opensearch_client,
    get_shorts_render_repository,
)
from app.modules.shorts.models import SavedShort
from app.modules.shorts.repository import SavedShortRepository
from app.modules.shorts_render.repository import ShortsRenderJobRepository
from app.modules.shorts.schemas import (
    SavedShortCreate,
    SavedShortResponse,
    SavedShortsListResponse,
)
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org
from app.modules.users.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shorts", tags=["shorts"])


def _to_response(short: SavedShort) -> SavedShortResponse:
    return SavedShortResponse(
        id=cast(UUID, short.id),
        video_id=short.video_id,
        scene_ids=short.scene_ids,
        title=short.title,
        start_ms=short.start_ms,
        end_ms=short.end_ms,
        created_at=short.created_at,
    )


@router.post("", response_model=SavedShortResponse, status_code=status.HTTP_201_CREATED)
async def create_saved_short(
    body: SavedShortCreate,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    repo: Annotated[SavedShortRepository, Depends(get_saved_short_repository)],
):
    user_id = cast(UUID, user.id)
    short = await repo.create(
        org_id=org_ctx.org_id,
        user_id=user_id,
        video_id=body.video_id,
        scene_ids=body.scene_ids,
        title=body.title,
        start_ms=body.start_ms,
        end_ms=body.end_ms,
    )
    return _to_response(short)


@router.get("", response_model=SavedShortsListResponse)
async def list_saved_shorts(
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    repo: Annotated[SavedShortRepository, Depends(get_saved_short_repository)],
):
    user_id = cast(UUID, user.id)
    shorts = await repo.list_by_user(org_ctx.org_id, user_id)
    return SavedShortsListResponse(
        shorts=[_to_response(short) for short in shorts],
        total=len(shorts),
    )


@router.delete("/{short_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_short(
    short_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    repo: Annotated[SavedShortRepository, Depends(get_saved_short_repository)],
):
    user_id = cast(UUID, user.id)
    short = await repo.get_by_id(short_id, org_ctx.org_id)
    if short is None or short.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved short not found",
        )

    await repo.delete(short)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{short_id}/composition")
async def get_short_composition(
    short_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    repo: Annotated[SavedShortRepository, Depends(get_saved_short_repository)],
    render_repo: Annotated[ShortsRenderJobRepository, Depends(get_shorts_render_repository)],
    scene_search=Depends(get_scene_opensearch_client),
):
    """Return a CompositionSpec for a saved short.

    If the short has a previous render job whose scene_ids match, return
    that job's input_spec.  Otherwise, generate a default composition
    from the saved short's scene_ids.
    """
    user_id = cast(UUID, user.id)
    short = await repo.get_by_id(short_id, org_ctx.org_id)
    if short is None or short.user_id != user_id:
        # Fallback for the auto-shorts product mode flow: the wizard
        # creates ShortsRenderJob rows directly (no SavedShort
        # wrapper), but the per-clip "스크립트 편집" / "렌더 결과
        # 보기" buttons still call this endpoint with the
        # render_job_id. Try the render-job table directly — same UUID
        # namespace, owner-scoped lookup so cross-user access stays a
        # 404. Returns the job's input_spec verbatim with
        # source="render_job" — identical to the primary path's
        # match-found return shape.
        render_job = await render_repo.get_by_id(
            org_ctx.org_id, user_id, short_id,
        )
        if render_job is not None and render_job.input_spec is not None:
            return {"composition": render_job.input_spec, "source": "render_job"}
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved short not found",
        )

    short_scene_set = set(short.scene_ids or [])

    # Try to find a render job whose scene_clips match this short
    jobs, _ = await render_repo.list_by_user(
        org_ctx.org_id, user_id, limit=50, offset=0,
    )
    for job in jobs:
        if job.video_id != short.video_id or not job.input_spec:
            continue
        job_scene_ids = {
            clip.get("scene_id")
            for clip in (job.input_spec.get("scene_clips") or [])
        }
        if job_scene_ids == short_scene_set:
            return {"composition": job.input_spec, "source": "render_job"}

    # Generate a default composition from scene_ids
    scene_ids = short.scene_ids or []
    if not scene_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Saved short has no scene IDs",
        )

    # Fetch scene boundaries from OpenSearch
    # doc_id format: "{org_id}:{scene_id}"
    org_id_str = str(org_ctx.org_id)
    doc_ids = [f"{org_id_str}:{sid}" for sid in scene_ids]
    scenes: list[dict[str, Any]] = []
    try:
        results = await scene_search.mget_scenes(doc_ids)
        scenes = [v for v in results.values() if v is not None]
    except Exception as exc:
        logger.warning("mget_scenes failed for short %s: %s", short_id, exc)

    if not scenes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not find scenes in index",
        )

    scene_clips = []
    timeline_offset = 0
    for scene_doc in scenes:
        start_ms = scene_doc.get("start_ms", 0)
        end_ms = scene_doc.get("end_ms", 0)
        clip = {
            "scene_id": scene_doc.get("scene_id", ""),
            "video_id": short.video_id,
            "source_type": scene_doc.get("source_type", "gdrive"),
            "start_ms": start_ms,
            "end_ms": end_ms,
            "timeline_start_ms": timeline_offset,
            "volume": 1.0,
            "crop_x": 0.0,
            "crop_y": 0.0,
            "crop_w": 1.0,
            "crop_h": 1.0,
        }
        scene_clips.append(clip)
        timeline_offset += end_ms - start_ms

    composition = {
        "output": {
            "width": 406,
            "height": 720,
            "fps": 30,
            "format": "mp4",
            "background_color": "#000000",
        },
        "scene_clips": scene_clips,
        "subtitles": [],
        "transitions": [],
        "title": short.title,
        "version": 1,
    }

    return {"composition": composition, "source": "generated"}
