from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db_session
from app.dependencies import get_agent_intent_repository, get_device_repository
from app.logging_config import get_logger
from app.modules.agent_intents.rate_limit import (
    check_create_rate_limit,
    check_exchange_rate_limit,
)
from app.modules.agent_intents.repository import AgentIntentRepository
from app.modules.agent_intents.schema_check import require_agent_intents_schema
from app.modules.agent_intents.schemas import (
    CreateIntentRequest,
    CreateIntentResponse,
    ExchangeIntentRequest,
    ExchangeIntentResponse,
    IntentListItem,
    IntentListResponse,
)
from app.modules.auth.dependencies import require_role
from app.modules.auth.service import get_current_user
from app.modules.devices.models import Device
from app.modules.devices.repository import DeviceRepository, verify_device_secret
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org
from app.modules.users.models import User, UserRole

logger = get_logger(__name__)

router = APIRouter(prefix="/agent-intents", tags=["agent-intents"])

_bearer_scheme = HTTPBearer()


async def _verify_device_secret_with_device(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    org_ctx: OrgContext = Depends(get_current_org),
    repo: DeviceRepository = Depends(get_device_repository),
    x_heimdex_device_id: str = Header(..., alias="X-Heimdex-Device-Id"),
) -> tuple[OrgContext, "Device"]:
    settings = get_settings()
    device = await repo.get_by_org_and_public_id(org_ctx.org_id, x_heimdex_device_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if device.is_revoked:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Device is revoked",
        )
    if not verify_device_secret(
        credentials.credentials,
        device.device_secret_hash,
        settings.device_secret_pepper,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid device secret",
        )
    return org_ctx, device


@router.post("/", response_model=CreateIntentResponse, status_code=status.HTTP_201_CREATED)
async def create_intent(
    body: CreateIntentRequest,
    org_ctx: OrgContext = Depends(get_current_org),
    db: AsyncSession = Depends(get_db_session),
    repo: AgentIntentRepository = Depends(get_agent_intent_repository),
    _admin: User = Depends(require_role(UserRole.ADMIN)),
    current_user: User = Depends(get_current_user),
):
    settings = get_settings()
    if not settings.agent_intents_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    require_agent_intents_schema()

    check_create_rate_limit(str(org_ctx.org_id))

    result = await db.execute(
        select(Device).where(
            Device.id == body.device_id,
            Device.org_id == org_ctx.org_id,
            Device.is_revoked.is_(False),
        )
    )
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    intent = await repo.create(
        org_id=org_ctx.org_id,
        type=body.type,
        created_by=current_user.id,
        device_id=device.id,
        ttl_minutes=settings.agent_intent_ttl_minutes,
    )

    logger.info(
        "agent_intent_created",
        org_slug=org_ctx.org_slug,
        intent_type=intent.type,
        intent_code_prefix=intent.intent_code[:4],
        device_id=str(intent.device_id),
    )

    return CreateIntentResponse(
        intent_code=intent.intent_code,
        type=intent.type,
        expires_at=intent.expires_at,
        deep_link_url=repo.build_deep_link_url(intent.type, intent.intent_code),
    )


@router.post("/exchange", response_model=ExchangeIntentResponse)
async def exchange_intent(
    body: ExchangeIntentRequest,
    verified: tuple[OrgContext, Device] = Depends(_verify_device_secret_with_device),
    repo: AgentIntentRepository = Depends(get_agent_intent_repository),
):
    settings = get_settings()
    if not settings.agent_intents_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    require_agent_intents_schema()

    org_ctx, device = verified
    check_exchange_rate_limit(str(device.id))
    intent = await repo.get_by_code_for_update(body.intent_code)

    if intent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intent not found")
    if intent.expires_at < datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Intent has expired",
        )
    if intent.used:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Intent has already been used",
        )
    if intent.org_id != org_ctx.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Intent does not belong to this organization",
        )
    if intent.device_id != device.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Intent is bound to a different device",
        )

    await repo.mark_used(intent, device.id)

    return ExchangeIntentResponse(
        type=intent.type,
        org_id=intent.org_id,
        payload=intent.payload,
    )


@router.get("/", response_model=IntentListResponse)
async def list_intents(
    org_ctx: OrgContext = Depends(get_current_org),
    repo: AgentIntentRepository = Depends(get_agent_intent_repository),
    _admin: User = Depends(require_role(UserRole.ADMIN)),
):
    settings = get_settings()
    if not settings.agent_intents_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    require_agent_intents_schema()
    intents = await repo.list_by_org(org_ctx.org_id)

    return IntentListResponse(
        intents=[
            IntentListItem(
                id=intent.id,
                type=intent.type,
                used=intent.used,
                expires_at=intent.expires_at,
                created_at=intent.created_at,
                created_by=intent.created_by,
            )
            for intent in intents
        ]
    )
