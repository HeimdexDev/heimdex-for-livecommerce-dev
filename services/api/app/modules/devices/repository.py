import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.devices.models import Device

_LAST_SEEN_STALE_MINUTES = 5


def hash_device_secret(raw_secret: str, pepper: str) -> str:
    """HMAC-SHA256(raw_secret, pepper) → hex digest."""
    return hmac.new(
        pepper.encode("utf-8"),
        raw_secret.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_device_secret(raw_secret: str, stored_hash: str, pepper: str) -> bool:
    computed = hash_device_secret(raw_secret, pepper)
    return hmac.compare_digest(computed, stored_hash)


def generate_device_secret() -> str:
    return secrets.token_urlsafe(32)


class DeviceRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_org_and_public_id(
        self, org_id: UUID, device_public_id: str
    ) -> Device | None:
        result = await self.session.execute(
            select(Device).where(
                Device.org_id == org_id,
                Device.device_public_id == device_public_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        org_id: UUID,
        device_name: str,
        device_public_id: str,
        device_secret_hash: str,
    ) -> Device:
        device = Device(
            org_id=org_id,
            device_name=device_name,
            device_public_id=device_public_id,
            device_secret_hash=device_secret_hash,
            is_revoked=False,
        )
        self.session.add(device)
        await self.session.flush()
        return device

    async def rotate_secret(
        self, device: Device, new_secret_hash: str
    ) -> Device:
        device.device_secret_hash = new_secret_hash
        await self.session.flush()
        return device

    async def revoke(self, device: Device) -> Device:
        device.is_revoked = True
        await self.session.flush()
        return device

    async def list_by_org(self, org_id: UUID, limit: int = 200) -> list[Device]:
        result = await self.session.execute(
            select(Device)
            .where(Device.org_id == org_id)
            .order_by(Device.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def update_last_seen(self, device: Device) -> None:
        now = datetime.now(UTC)
        if device.last_seen_at is not None:
            threshold = now - timedelta(minutes=_LAST_SEEN_STALE_MINUTES)
            if device.last_seen_at > threshold:
                return

        await self.session.execute(
            update(Device)
            .where(Device.id == device.id)
            .values(last_seen_at=now)
        )
