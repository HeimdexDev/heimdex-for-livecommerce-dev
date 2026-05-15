from __future__ import annotations

from datetime import datetime
from typing import Any, final
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


@final
class SearchEvent(Base):
    # Uses (BIGSERIAL, created_at) composite PK instead of UUIDMixin for partition compatibility.
    # No TimestampMixin — events are immutable (no updated_at).

    __tablename__ = "search_events"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    org_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    search_mode: Mapped[str] = mapped_column(Text, nullable=False)
    result_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default="{}",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        # Tell SQLAlchemy this is a partitioned table — don't try to create it
        # via metadata.create_all.  Alembic migration handles DDL.
        {"implicit_returning": False},
    )
