from fastapi import APIRouter, Depends

from app.dependencies import get_search_service
from app.logging_config import get_logger
from app.modules.auth import get_current_user
from app.modules.search.schemas import SearchRequest, SearchResponse
from app.modules.search.service import SearchService
from app.modules.tenancy import OrgContext, get_current_org
from app.modules.users.models import User

logger = get_logger(__name__)
router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    search_service: SearchService = Depends(get_search_service),
):
    logger.debug("search_request", user_id=str(user.id), org_id=str(org_ctx.org_id))
    return await search_service.search(
        query=request.q,
        org_id=org_ctx.org_id,
        alpha=request.alpha,
        filters=request.filters,
    )
