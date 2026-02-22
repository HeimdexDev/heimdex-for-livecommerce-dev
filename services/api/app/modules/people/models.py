from datetime import datetime
from typing import final
from uuid import UUID as PyUUID

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class DriveNicknameRegistry(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "drive_nickname_registry"
    
    org_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_fingerprint_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    nickname: Mapped[str] = mapped_column(String(100), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    
    __table_args__ = (
        {"comment": "Registry of removable drive nicknames for display in UI"},
    )


class PeopleClusterLabel(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "people_cluster_labels"
    
    org_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    person_cluster_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    
    __table_args__ = (
        UniqueConstraint(
            "org_id", "person_cluster_id",
            name="uq_people_cluster_labels_org_person",
        ),
        {"comment": "Labels for face clusters within an org"},
    )


@final
class PeopleExcludePreference(Base, UUIDMixin, TimestampMixin):
    """User-specific face exclusion preferences.

    Labels are org-wide (everyone sees "장원영"), but exclusion filters
    are user-specific (only I exclude "장원영" from my search results).
    """

    __tablename__ = "people_exclude_preferences"

    org_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    person_cluster_id: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__: tuple[object, ...] = (
        UniqueConstraint(
            "org_id", "user_id", "person_cluster_id",
            name="uq_people_exclude_prefs_org_user_person",
        ),
        Index("ix_people_exclude_prefs_org_user", "org_id", "user_id"),
        {"comment": "Per-user face exclusion preferences for search filtering"},
    )
