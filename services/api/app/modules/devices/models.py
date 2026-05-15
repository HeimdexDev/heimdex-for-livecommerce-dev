from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class Device(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "devices"

    org_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    device_name: Mapped[str] = mapped_column(String(255), nullable=False)
    device_public_id: Mapped[str] = mapped_column(String(64), nullable=False)
    device_secret_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    is_revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("org_id", "device_public_id"),
    )
