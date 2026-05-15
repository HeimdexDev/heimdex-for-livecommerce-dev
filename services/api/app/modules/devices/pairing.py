import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, delete, select
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class PairingCode(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "pairing_codes"

    org_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(6), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    used_by_device_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("devices.id"),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint("org_id", "code", name="uq_pairing_codes_org_id_code"),
    )


def generate_pairing_code() -> str:
    """Generate a cryptographically secure 6-digit pairing code."""
    return f"{secrets.randbelow(1000000):06d}"


class PairingCodeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, *, org_id: UUID, ttl_minutes: int = 10) -> PairingCode:
        """Create a new pairing code for the org.

        Also performs lazy cleanup of expired codes for this org.
        """
        await self._cleanup_expired(org_id)

        code = generate_pairing_code()
        pairing = PairingCode(
            org_id=org_id,
            code=code,
            expires_at=datetime.now(UTC) + timedelta(minutes=ttl_minutes),
            used=False,
        )
        self.session.add(pairing)
        await self.session.flush()
        return pairing

    async def get_by_org_and_code(
        self, org_id: UUID, code: str
    ) -> PairingCode | None:
        """Look up a pairing code within an org (no row lock)."""
        result = await self.session.execute(
            select(PairingCode).where(
                PairingCode.org_id == org_id,
                PairingCode.code == code,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_org_and_code_for_update(
        self, org_id: UUID, code: str
    ) -> PairingCode | None:
        """Look up a pairing code with a row-level lock for atomic exchange."""
        result = await self.session.execute(
            select(PairingCode)
            .where(
                PairingCode.org_id == org_id,
                PairingCode.code == code,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def mark_used(self, pairing: PairingCode, device_id: UUID) -> None:
        """Atomically mark a pairing code as used."""
        pairing.used = True
        pairing.used_by_device_id = device_id
        await self.session.flush()

    async def _cleanup_expired(self, org_id: UUID) -> None:
        """Delete expired and unused pairing codes for the org."""
        now = datetime.now(UTC)
        await self.session.execute(
            delete(PairingCode).where(
                PairingCode.org_id == org_id,
                PairingCode.expires_at < now,
                PairingCode.used == False,  # noqa: E712
            )
        )
