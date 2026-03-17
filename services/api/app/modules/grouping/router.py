from fastapi import APIRouter, Depends, Query

from app.dependencies import get_grouping_service
from app.modules.auth import get_current_user
from app.modules.grouping.schemas import SceneGroupsResponse
from app.modules.grouping.service import GroupingService
from app.modules.tenancy import OrgContext, get_current_org
from app.modules.users.models import User

router = APIRouter(prefix="/videos", tags=["grouping"])


@router.get(
    "/{video_id}/scene-groups",
    response_model=SceneGroupsResponse,
)
async def get_scene_groups(
    video_id: str,
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    service: GroupingService = Depends(get_grouping_service),
    threshold: float | None = Query(
        None, ge=0.0, le=1.0,
        description="Similarity threshold override. When omitted, uses adaptive threshold.",
    ),
    sensitivity: float = Query(
        1.0, ge=0.0, le=3.0,
        description="Adaptive threshold sensitivity (std devs below mean). Higher = fewer groups.",
    ),
):
    _ = user
    return await service.get_scene_groups(
        str(org_ctx.org_id),
        video_id,
        threshold=threshold,
        sensitivity=sensitivity,
    )
