import hmac
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db_session
from app.logging_config import get_logger
from app.modules.auth.dependencies import require_role
from app.modules.devices.repository import (
    DeviceRepository,
    generate_device_secret,
    hash_device_secret,
    verify_device_secret,
)
from app.modules.devices.schemas import (
    DeviceListItem,
    DeviceListResponse,
    DeviceRegisterRequest,
    DeviceRegisterResponse,
    DeviceRevokeRequest,
    DeviceRevokeResponse,
    DeviceRotateRequest,
    DeviceRotateResponse,
)
from app.modules.orgs.models import Org
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org
from app.modules.users.models import UserRole

logger = get_logger(__name__)

router = APIRouter(prefix="/devices", tags=["devices"])

_bearer_scheme = HTTPBearer()


async def _verify_org_api_key(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    org_ctx: OrgContext = Depends(get_current_org),
    db: AsyncSession = Depends(get_db_session),
) -> OrgContext:
    settings = get_settings()

    if not settings.agent_ingest_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agent ingestion is disabled",
        )

    result = await db.execute(select(Org).where(Org.id == org_ctx.org_id))
    org = result.scalar_one_or_none()

    token = credentials.credentials
    org_api_key = org.agent_api_key if org else None

    if org_api_key and hmac.compare_digest(token, org_api_key):
        return org_ctx

    if hmac.compare_digest(token, settings.agent_api_key):
        return org_ctx

    logger.warning("device_register_invalid_token", org_slug=org_ctx.org_slug)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key for device registration",
    )


async def _verify_device_secret(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    org_ctx: OrgContext = Depends(get_current_org),
    db: AsyncSession = Depends(get_db_session),
    x_heimdex_device_id: str = Header(..., alias="X-Heimdex-Device-Id"),
) -> OrgContext:
    settings = get_settings()
    repo = DeviceRepository(db)

    device = await repo.get_by_org_and_public_id(org_ctx.org_id, x_heimdex_device_id)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )
    if device.is_revoked:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Device is revoked",
        )

    if not verify_device_secret(
        credentials.credentials, device.device_secret_hash, settings.device_secret_pepper
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid device secret",
        )

    return org_ctx


@router.post(
    "/register",
    response_model=DeviceRegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_device(
    body: DeviceRegisterRequest,
    org_ctx: OrgContext = Depends(_verify_org_api_key),
    db: AsyncSession = Depends(get_db_session),
):
    settings = get_settings()
    repo = DeviceRepository(db)

    existing = await repo.get_by_org_and_public_id(org_ctx.org_id, body.device_public_id)
    if existing is not None:
        if existing.is_revoked:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Device is revoked.",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Device already registered. Use POST /api/devices/rotate to get a new secret.",
        )

    raw_secret = generate_device_secret()
    secret_hash = hash_device_secret(raw_secret, settings.device_secret_pepper)

    device = await repo.create(
        org_id=org_ctx.org_id,
        device_name=body.device_name,
        device_public_id=body.device_public_id,
        device_secret_hash=secret_hash,
    )

    logger.info(
        "device_registered",
        org_slug=org_ctx.org_slug,
        device_public_id=body.device_public_id,
        device_name=body.device_name,
    )

    return DeviceRegisterResponse(
        device_id=device.id,
        device_public_id=device.device_public_id,
        device_name=device.device_name,
        device_secret=raw_secret,
        created_at=device.created_at,
    )


@router.post("/rotate", response_model=DeviceRotateResponse)
async def rotate_device_secret(
    body: DeviceRotateRequest,
    org_ctx: OrgContext = Depends(_verify_device_secret),
    db: AsyncSession = Depends(get_db_session),
):
    settings = get_settings()
    repo = DeviceRepository(db)

    device = await repo.get_by_org_and_public_id(org_ctx.org_id, body.device_public_id)
    if device is None or device.is_revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found or revoked",
        )

    raw_secret = generate_device_secret()
    secret_hash = hash_device_secret(raw_secret, settings.device_secret_pepper)

    await repo.rotate_secret(device, secret_hash)

    logger.info(
        "device_secret_rotated",
        org_slug=org_ctx.org_slug,
        device_public_id=body.device_public_id,
    )

    return DeviceRotateResponse(
        device_id=device.id,
        device_public_id=device.device_public_id,
        device_secret=raw_secret,
        rotated_at=datetime.now(UTC),
    )


@router.post("/revoke", response_model=DeviceRevokeResponse)
async def revoke_device(
    body: DeviceRevokeRequest,
    org_ctx: OrgContext = Depends(get_current_org),
    db: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role(UserRole.ADMIN)),
):
    repo = DeviceRepository(db)

    device = await repo.get_by_org_and_public_id(org_ctx.org_id, body.device_public_id)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )
    if device.is_revoked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Device is already revoked",
        )

    await repo.revoke(device)

    logger.info(
        "device_revoked",
        org_slug=org_ctx.org_slug,
        device_public_id=body.device_public_id,
    )

    return DeviceRevokeResponse(
        device_id=device.id,
        device_public_id=body.device_public_id,
        is_revoked=True,
        revoked_at=datetime.now(UTC),
    )


@router.get("/", response_model=DeviceListResponse)
async def list_devices(
    org_ctx: OrgContext = Depends(get_current_org),
    db: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role(UserRole.ADMIN)),
):
    repo = DeviceRepository(db)
    devices = await repo.list_by_org(org_ctx.org_id)

    return DeviceListResponse(
        devices=[
            DeviceListItem(
                device_id=d.id,
                device_public_id=d.device_public_id,
                device_name=d.device_name,
                is_revoked=d.is_revoked,
                last_seen_at=d.last_seen_at,
                created_at=d.created_at,
            )
            for d in devices
        ]
    )
