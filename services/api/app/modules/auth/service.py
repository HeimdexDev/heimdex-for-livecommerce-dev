from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db_session
from app.logging_config import get_logger
from app.modules.auth.oidc import validate_auth0_token, fetch_userinfo, Auth0TokenPayload
from app.modules.auth.schemas import TokenPayload
from app.modules.tenancy import OrgContext, get_current_org
from app.modules.users.models import User
from app.modules.users.repository import UserRepository

logger = get_logger(__name__)
security = HTTPBearer(auto_error=False)


class AuthService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.settings = get_settings()

    async def get_user_by_email(self, email: str, org_id: UUID) -> User | None:
        """Get user by email within an organization.
        
        This method provides a clean interface for auth operations to look up users
        without directly accessing the UserRepository from other modules.
        """
        user_repo = UserRepository(self.session)
        return await user_repo.get_by_email(email, org_id)

    def create_access_token(
        self,
        user_id: UUID,
        org_id: UUID,
        email: str,
        role: str,
    ) -> str:
        settings = get_settings()
        expire = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expiration_hours)
        
        payload = {
            "sub": str(user_id),
            "org_id": str(org_id),
            "user_id": str(user_id),
            "email": email,
            "role": role,
            "exp": int(expire.timestamp()),
        }
        
        return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

    def decode_token(self, token: str) -> TokenPayload:
        settings = get_settings()
        try:
            payload = jwt.decode(
                token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
            )
            return TokenPayload(**payload)
        except JWTError as e:
            logger.warning("jwt_decode_failed", error=str(e))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            ) from e


async def get_current_user(
    org_ctx: OrgContext = Depends(get_current_org),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db_session),
) -> User:
    if not credentials:
        logger.warning("auth_no_credentials", org_slug=org_ctx.org_slug)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
        )
    
    settings = get_settings()
    token = credentials.credentials
    logger.debug("auth_credentials_received", org_slug=org_ctx.org_slug)
    user_repo = UserRepository(db)
    
    if settings.auth0_enabled:
        return await _validate_auth0_user(token, org_ctx, user_repo)
    else:
        return await _validate_dev_user(token, org_ctx, user_repo, db)


def _enforce_org_binding(auth0_payload: Auth0TokenPayload, org_ctx: OrgContext) -> None:
    """Enforce org binding via subdomain + optional token org_id.

    The subdomain is the source of truth for org identity (server-controlled).
    User lookup is always scoped to org_ctx.org_id, so cross-tenant access is
    impossible even without org_id in the token.

    If org_id IS present in the token, it must match — reject mismatches.
    If org_id is absent, allow it — the org-scoped user lookup is sufficient.
    """
    token_org_id = auth0_payload.org_id

    if not token_org_id:
        logger.debug("org_binding_skip_no_token_org", org_slug=org_ctx.org_slug)
        return

    expected = org_ctx.auth0_org_id or str(org_ctx.org_id)
    if token_org_id != expected:
        logger.warning(
            "org_mismatch",
            org_slug=org_ctx.org_slug,
            token_org_id=token_org_id,
            expected_org_id=expected,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token organization does not match request",
        )


async def _validate_auth0_user(
    token: str,
    org_ctx: OrgContext,
    user_repo: UserRepository,
) -> User:
    try:
        auth0_payload = validate_auth0_token(token)
    except ValueError as e:
        logger.warning("auth0_validation_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        ) from e
    
    _enforce_org_binding(auth0_payload, org_ctx)
    
    user = await user_repo.get_by_auth0_sub(auth0_payload.sub, org_ctx.org_id)
    
    if not user:
        email = auth0_payload.email
        email_verified = auth0_payload.raw_claims.get("email_verified", False)
        
        # Auth0 access tokens don't include email by default.
        # Fall back to /userinfo endpoint to get email + verification status.
        if not email:
            logger.info("auth0_email_missing_from_token", sub=auth0_payload.sub)
            userinfo = fetch_userinfo(token)
            email = userinfo.get("email")
            email_verified = userinfo.get("email_verified", False)
        
        if email and not email_verified:
            logger.warning("auth0_email_not_verified", email=email, sub=auth0_payload.sub)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Email not verified. Please verify your email before accessing this organization.",
            )
        
        if email:
            user = await user_repo.get_by_email(email, org_ctx.org_id)
            if user:
                await user_repo.link_auth0_sub(user.id, auth0_payload.sub)
                logger.info(
                    "linked_auth0_sub_to_user",
                    user_id=str(user.id),
                    sub=auth0_payload.sub,
                    email=email,
                )
            else:
                # Auto-provision: Auth0 org membership + verified email = trusted user.
                # Admin adds users to the Auth0 organization; on first login we
                # create their DB row automatically so no manual SQL is needed.
                # SAVEPOINT handles the race where parallel requests both try to INSERT.
                try:
                    async with user_repo.session.begin_nested():
                        user = await user_repo.create(org_ctx.org_id, email)
                    await user_repo.link_auth0_sub(user.id, auth0_payload.sub)
                    logger.info(
                        "auto_provisioned_user",
                        user_id=str(user.id),
                        sub=auth0_payload.sub,
                        email=email,
                        org_id=str(org_ctx.org_id),
                    )
                except IntegrityError:
                    user = await user_repo.get_by_email(email, org_ctx.org_id)
                    if user:
                        await user_repo.link_auth0_sub(user.id, auth0_payload.sub)
                        logger.info(
                            "linked_auth0_sub_after_race",
                            user_id=str(user.id),
                            sub=auth0_payload.sub,
                            email=email,
                        )
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found. Contact your organization admin.",
        )
    
    return user


async def _validate_dev_user(
    token: str,
    org_ctx: OrgContext,
    user_repo: UserRepository,
    db: AsyncSession,
) -> User:
    auth_service = AuthService(db)
    payload = auth_service.decode_token(token)
    
    if UUID(payload.org_id) != org_ctx.org_id:
        logger.warning(
            "org_mismatch_in_token",
            token_org=payload.org_id,
            request_org=str(org_ctx.org_id),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token organization does not match request",
        )
    
    user = await user_repo.get_by_id(UUID(payload.user_id), org_ctx.org_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    
    return user
