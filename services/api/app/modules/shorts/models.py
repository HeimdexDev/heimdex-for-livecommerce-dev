from typing import final
from uuid import UUID

from sqlalchemy import JSON, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


@final
class SavedShort(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "saved_shorts"

    org_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    video_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scene_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    start_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__: tuple[object, ...] = (
        Index("ix_saved_shorts_org_id_user_id", "org_id", "user_id"),
    )
