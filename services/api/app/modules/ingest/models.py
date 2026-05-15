from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IdempotencyKey(Base):
    """Persistent idempotency key for agent ingest replay protection.

    Replaces the in-memory OrderedDict cache that was lost on API restarts.
    Uses INSERT ... ON CONFLICT DO NOTHING for atomic dedup.
    Expired rows are periodically cleaned by the application.
    """

    __tablename__ = "ingest_idempotency_keys"

    key: Mapped[str] = mapped_column(String(256), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
