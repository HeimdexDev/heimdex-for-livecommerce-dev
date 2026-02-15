from fastapi import APIRouter, Depends, HTTPException, status

from app.config import get_settings
from app.dependencies import get_auth_service
from app.logging_config import get_logger
from app.modules.auth.schemas import DevLoginRequest, DevLoginResponse
from app.modules.auth.service import AuthService, get_current_user
from app.modules.tenancy import OrgContext, get_current_org
from app.modules.users.models import User

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/dev-login", response_model=DevLoginResponse)
async def dev_login(
    request: DevLoginRequest,
    org_ctx: OrgContext = Depends(get_current_org),
    auth_service: AuthService = Depends(get_auth_service),
):
    settings = get_settings()
    if settings.environment != "development":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dev login only available in development environment",
        )
    
    # Use auth_service method instead of direct repository access
    user = await auth_service.get_user_by_email(request.email, org_ctx.org_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with email {request.email} not found in org {org_ctx.org_slug}",
        )
    
    token = auth_service.create_access_token(
        user_id=user.id,
        org_id=org_ctx.org_id,
        email=user.email,
        role=str(user.role),
    )
    
    logger.info("dev_login_success", user_id=str(user.id), org_id=str(org_ctx.org_id))
    
    return DevLoginResponse(
        access_token=token,
        user_id=user.id,
        org_id=org_ctx.org_id,
        org_slug=org_ctx.org_slug,
    )


@router.post("/dev-refresh", response_model=DevLoginResponse)
async def dev_refresh(
    org_ctx: OrgContext = Depends(get_current_org),
    user: "User" = Depends(get_current_user),
):
    settings = get_settings()
    if settings.environment != "development":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dev refresh only available in development environment",
        )
    if not settings.enable_dev_refresh:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dev refresh is disabled",
        )

    from typing import cast

    from sqlalchemy.ext.asyncio import AsyncSession

    auth_service = AuthService(cast(AsyncSession, object()))
    token = auth_service.create_access_token(
        user_id=user.id,
        org_id=org_ctx.org_id,
        email=user.email,
        role=str(user.role),
    )

    return DevLoginResponse(
        access_token=token,
        user_id=user.id,
        org_id=org_ctx.org_id,
        org_slug=org_ctx.org_slug,
    )
