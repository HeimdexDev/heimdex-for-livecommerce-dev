from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.modules.orgs.models import Org


class UserRole(str, Enum):
    ADMIN = "admin"
    MEMBER = "member"


class User(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "users"
    
    org_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(String(20), nullable=False, default=UserRole.MEMBER)
    auth0_sub: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    
    org: Mapped["Org"] = relationship("Org", back_populates="users")
    
    __table_args__ = (
        UniqueConstraint("org_id", "email", name="uq_users_org_id_email"),
        {"comment": "Users table with org-scoped emails and Auth0 subject ID"},
    )
