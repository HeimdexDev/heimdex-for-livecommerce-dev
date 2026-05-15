from typing import Any, final
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


@final
class SubtitlePreset(Base, UUIDMixin, TimestampMixin):
    """User-saved style preset for the shorts editor's text/background panel.

    Visibility model:
    - Always visible to the creator (``user_id``).
    - Also visible to every user in ``org_id`` when ``is_shared = True``.
    - Mutations (rename, restyle, share toggle, delete) restricted to creator.

    The ``style_json`` blob holds a fragment of the contracts overlay spec
    — only the visual fields, not position / timing / layer_index. Apply-
    preset on the frontend merges these into an existing overlay.
    """

    __tablename__ = "subtitle_presets"

    org_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    style_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    is_shared: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    __table_args__: tuple[object, ...] = (
        Index("ix_subtitle_presets_org_user", "org_id", "user_id"),
    )
