from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db_session, get_org_repository
from app.logging_config import get_logger
from app.modules.auth import get_current_user
from app.modules.orgs.repository import OrgRepository
from app.modules.orgs.schemas import OrgSettingsResponse, OrgSettingsUpdateRequest
from app.modules.tenancy import OrgContext, get_current_org
from app.modules.users.models import User

logger = get_logger(__name__)
router = APIRouter(prefix="/org", tags=["org"])


@router.get("/settings", response_model=OrgSettingsResponse)
async def get_org_settings(
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    org_repo: OrgRepository = Depends(get_org_repository),
):
    """Get organization settings with defaults merged."""
    org = await org_repo.get_by_id(org_ctx.org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    merged = org.get_settings_with_defaults()
    return OrgSettingsResponse(**merged)


@router.patch("/settings", response_model=OrgSettingsResponse)
async def update_org_settings(
    request: OrgSettingsUpdateRequest,
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    org_repo: OrgRepository = Depends(get_org_repository),
    db: AsyncSession = Depends(get_db_session),
):
    """Update organization settings."""
    patch = request.model_dump(exclude_none=True)
    if not patch:
        # No fields to update — just return current settings
        org = await org_repo.get_by_id(org_ctx.org_id)
        if not org:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
        merged = org.get_settings_with_defaults()
        return OrgSettingsResponse(**merged)

    org = await org_repo.update_settings(org_ctx.org_id, patch)
    await db.commit()
    merged = org.get_settings_with_defaults()
    logger.info("org_settings_updated", org_id=str(org_ctx.org_id), updated_fields=list(patch.keys()))
    return OrgSettingsResponse(**merged)
