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
    threshold: float = Query(
        0.55, ge=0.0, le=1.0,
        description="Similarity threshold for group boundaries",
    ),
):
    _ = user
    return await service.get_scene_groups(
        str(org_ctx.org_id),
        video_id,
        threshold=threshold,
    )
