from uuid import UUID as PyUUID

from sqlalchemy import Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.db.base import Base, TimestampMixin, UUIDMixin


class FaceIdentity(Base, UUIDMixin, TimestampMixin):
    __tablename__: str = "face_identities"

    org_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cluster_id: Mapped[str] = mapped_column(String(64), nullable=False)
    centroid_embedding: Mapped[list[float]] = mapped_column(
        type_=Vector(512),
        nullable=False,
    )
    exemplar_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    best_quality: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    best_thumbnail_video_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    thumbnail_source: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="auto",
    )  # auto | exemplar | upload
    selected_exemplar_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("face_exemplars.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__: tuple[object, ...] = (
        UniqueConstraint("org_id", "cluster_id", name="uq_face_identities_org_cluster"),
        Index("ix_face_identities_org_id", "org_id"),
        {"comment": "Face identity centroids for cross-video person matching (pgvector)"},
    )


class FaceExemplar(Base, UUIDMixin, TimestampMixin):
    __tablename__: str = "face_exemplars"

    identity_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("face_identities.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    video_id: Mapped[str] = mapped_column(String(255), nullable=False)
    scene_id: Mapped[str] = mapped_column(String(255), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(type_=Vector(512), nullable=False)
    quality: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    bbox_json: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)

    __table_args__: tuple[object, ...] = (
        Index("ix_face_exemplars_identity", "identity_id"),
        Index("ix_face_exemplars_org_video", "org_id", "video_id"),
        {"comment": "Individual face exemplars linked to identities"},
    )
