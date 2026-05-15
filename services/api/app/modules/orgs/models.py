from typing import Any

from sqlalchemy import String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

User = Any
Library = Any

SETTINGS_DEFAULTS: dict[str, Any] = {
    "thumbnail_aspect_ratio": "16:9",
    "split_preset": "default",
}


class Org(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "orgs"

    slug: Mapped[str] = mapped_column(String(63), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    auth0_org_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    agent_api_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )

    users: Mapped[list[User]] = relationship("User", back_populates="org", lazy="selectin")
    libraries: Mapped[list[Library]] = relationship("Library", back_populates="org", lazy="selectin")

    def get_settings_with_defaults(self) -> dict[str, Any]:
        merged = dict(SETTINGS_DEFAULTS)
        merged.update(self.settings or {})
        return merged
