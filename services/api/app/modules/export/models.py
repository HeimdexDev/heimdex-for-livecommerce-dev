"""SQLAlchemy model for export_records table.

Tracks async proxy-pack export jobs: status, S3 location, cache hash, and expiry.
"""
from datetime import datetime
from typing import Any, Optional, final
from typing import Optional, final
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


@final
class ExportRecord(Base, UUIDMixin, TimestampMixin):
    """A single async export job (proxy-pack or future variants)."""

    __tablename__ = "export_records"

    org_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=False,
    )


    export_hash: Mapped[str] = mapped_column(String(16), nullable=False)


    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


    s3_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    clip_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    proxy_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


    sequence_name: Mapped[str] = mapped_column(String(200), nullable=False, server_default="Heimdex Export")
    request_body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__: tuple[object, ...] = (
        Index("ix_export_records_org_hash", "org_id", "export_hash"),
    )
