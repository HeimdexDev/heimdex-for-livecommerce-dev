from datetime import datetime
from typing import final
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


@final
class TextTemplate(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "text_templates"

    org_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    font_family: Mapped[str] = mapped_column(
        String(100), nullable=False, server_default="Noto Sans KR"
    )
    font_size_px: Mapped[int] = mapped_column(Integer, nullable=False, server_default="48")
    font_color: Mapped[str] = mapped_column(String(9), nullable=False, server_default="#FFFFFF")
    font_weight: Mapped[int] = mapped_column(Integer, nullable=False, server_default="700")
    line_height: Mapped[float] = mapped_column(Float, nullable=False, server_default="1.4")
    letter_spacing: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    position_x: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.5")
    position_y: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.85")
    text_align: Mapped[str] = mapped_column(String(10), nullable=False, server_default="center")
    shadow_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    shadow_color: Mapped[str] = mapped_column(String(9), nullable=False, server_default="#000000")
    shadow_offset_x: Mapped[int] = mapped_column(Integer, nullable=False, server_default="2")
    shadow_offset_y: Mapped[int] = mapped_column(Integer, nullable=False, server_default="2")
    shadow_blur: Mapped[int] = mapped_column(Integer, nullable=False, server_default="4")
    background_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    background_color: Mapped[str | None] = mapped_column(String(9), nullable=True)
    background_padding: Mapped[int] = mapped_column(Integer, nullable=False, server_default="8")
    is_system_preset: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    __table_args__: tuple[object, ...] = (
        Index("ix_text_templates_org_user", "org_id", "user_id"),
    )
