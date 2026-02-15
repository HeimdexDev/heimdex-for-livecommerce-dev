"""
Agent authentication for the ingest endpoint.

Supports three modes via agent_api_key_mode:
- "global": single shared key (legacy default)
- "per-org": per-org API key
- "per-device": per-device secret with HMAC-SHA256 + server pepper

Security:
- Constant-time comparison via hmac.compare_digest
- Per-device mode rejects org API keys for ingest (prevents downgrade)
- Device revocation checked on every request (no cache)
"""
import hmac

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db_session
from app.logging_config import get_logger
from app.modules.devices.repository import DeviceRepository, verify_device_secret
from app.modules.orgs.models import Org
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org

logger = get_logger(__name__)

_bearer_scheme = HTTPBearer()


async def verify_agent_token(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    org_ctx: OrgContext = Depends(get_current_org),
    db: AsyncSession = Depends(get_db_session),
    x_heimdex_device_id: str | None = Header(None, alias="X-Heimdex-Device-Id"),
) -> OrgContext:
    """
    Validate agent Bearer token and return resolved org context.

    In per-device mode, validates HMAC-SHA256(token, pepper) against the
    device's stored hash and checks revocation. Org API keys are rejected
    to prevent downgrade attacks that would bypass device-level revocation.
    """
    settings = get_settings()

    if not settings.agent_ingest_enabled:
        logger.warning("agent_ingest_disabled", org_slug=org_ctx.org_slug)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agent ingestion is disabled",
        )

    token = credentials.credentials
    mode = settings.agent_api_key_mode

    if mode == "per-device":
        if not x_heimdex_device_id:
            logger.warning(
                "agent_ingest_missing_device_id",
                org_slug=org_ctx.org_slug,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="X-Heimdex-Device-Id header required in per-device mode",
            )

        repo = DeviceRepository(db)
        device = await repo.get_by_org_and_public_id(
            org_ctx.org_id, x_heimdex_device_id
        )

        if device is None:
            logger.warning(
                "agent_ingest_device_not_found",
                org_slug=org_ctx.org_slug,
                device_public_id=x_heimdex_device_id,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Device not registered",
            )

        if device.is_revoked:
            logger.warning(
                "agent_ingest_device_revoked",
                org_slug=org_ctx.org_slug,
                device_public_id=x_heimdex_device_id,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Device is revoked",
            )

        if not verify_device_secret(
            token, device.device_secret_hash, settings.device_secret_pepper
        ):
            logger.warning(
                "agent_ingest_invalid_device_secret",
                org_slug=org_ctx.org_slug,
                device_public_id=x_heimdex_device_id,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid device secret",
            )

        await repo.update_last_seen(device)

        logger.debug(
            "agent_device_token_verified",
            org_id=str(org_ctx.org_id),
            org_slug=org_ctx.org_slug,
            device_public_id=x_heimdex_device_id,
        )
        return org_ctx

    # --- global / per-org modes (existing behavior) ---
    org_api_key: str | None = None
    if hasattr(db, "execute"):
        result = await db.execute(select(Org).where(Org.id == org_ctx.org_id))
        org = result.scalar_one_or_none()
        if org is not None:
            org_api_key = org.agent_api_key

    if mode == "per-org":
        if not org_api_key or not hmac.compare_digest(token, org_api_key):
            logger.warning(
                "agent_ingest_invalid_token",
                org_slug=org_ctx.org_slug,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid agent API key",
            )
    elif org_api_key:
        if not hmac.compare_digest(token, org_api_key):
            logger.warning(
                "agent_ingest_invalid_token",
                org_slug=org_ctx.org_slug,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid agent API key",
            )
    else:
        logger.warning("agent_ingest_global_fallback", org_slug=org_ctx.org_slug)
        if not hmac.compare_digest(token, settings.agent_api_key):
            logger.warning(
                "agent_ingest_invalid_token",
                org_slug=org_ctx.org_slug,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid agent API key",
            )

    logger.debug(
        "agent_token_verified",
        org_id=str(org_ctx.org_id),
        org_slug=org_ctx.org_slug,
    )
    return org_ctx
