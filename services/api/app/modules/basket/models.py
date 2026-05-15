from typing import final
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


@final
class SceneBasket(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "scene_baskets"

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
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="Untitled")

    __table_args__: tuple[object, ...] = (
        Index("ix_scene_baskets_org_user", "org_id", "user_id"),
    )


@final
class SceneBasketItem(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "scene_basket_items"

    basket_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("scene_baskets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scene_id: Mapped[str] = mapped_column(String(255), nullable=False)
    video_id: Mapped[str] = mapped_column(String(64), nullable=False)
    video_title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__: tuple[object, ...] = (
        UniqueConstraint("basket_id", "scene_id", name="uq_basket_items_basket_scene"),
        Index("ix_scene_basket_items_basket_id", "basket_id"),
    )
