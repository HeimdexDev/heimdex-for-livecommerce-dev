import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agent_intents.models import AgentIntent

DEEP_LINK_ACTIONS = {
    "folder_add": "add-folder",
}


def generate_intent_code() -> str:
    return secrets.token_urlsafe(18)


class AgentIntentRepository:
    def __init__(self, session: AsyncSession):
        self.session: AsyncSession = session

    async def create(
        self,
        *,
        org_id: UUID,
        type: str,
        created_by: UUID,
        device_id: UUID,
        ttl_minutes: int = 10,
        payload: dict[str, object] | None = None,
    ) -> AgentIntent:
        await self._cleanup_expired(org_id)
        code = generate_intent_code()
        intent = AgentIntent(
            org_id=org_id,
            type=type,
            intent_code=code,
            payload=payload or {},
            expires_at=datetime.now(UTC) + timedelta(minutes=ttl_minutes),
            created_by=created_by,
            device_id=device_id,
            used=False,
        )
        self.session.add(intent)
        await self.session.flush()
        return intent

    async def get_by_code_for_update(self, intent_code: str) -> AgentIntent | None:
        result = await self.session.execute(
            select(AgentIntent)
            .where(AgentIntent.intent_code == intent_code)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def mark_used(self, intent: AgentIntent, device_id: UUID) -> None:
        intent.used = True
        intent.used_by_device_id = device_id
        intent.used_at = datetime.now(UTC)
        await self.session.flush()

    async def list_by_org(self, org_id: UUID, limit: int = 50) -> list[AgentIntent]:
        result = await self.session.execute(
            select(AgentIntent)
            .where(AgentIntent.org_id == org_id)
            .order_by(AgentIntent.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def _cleanup_expired(self, org_id: UUID) -> None:
        now = datetime.now(UTC)
        _ = await self.session.execute(
            delete(AgentIntent).where(
                AgentIntent.org_id == org_id,
                AgentIntent.expires_at < now,
                AgentIntent.used.is_(False),
            )
        )

    @staticmethod
    def build_deep_link_url(intent_type: str, intent_code: str) -> str:
        action = DEEP_LINK_ACTIONS.get(intent_type, intent_type)
        return f"heimdex://{action}?code={intent_code}"
