"""
SQLAlchemy models for Google Drive integration.

Tables:
- drive_connections: Tracks which Shared Drives are connected per org.
- drive_files: Tracks every video file discovered in connected Shared Drives.
- drive_secrets: Encrypted storage for Google service account keys (AES-256-GCM).

Design decisions (from ARCHITECTURE.md):
- All tables FK to orgs.id with CASCADE delete (multi-tenant isolation).
- drive_files.video_id is deterministic: "gd_{sha256(org_id:google_file_id)[:16]}".
- processing_status is a text enum enforced at application layer (not DB CHECK)
  to allow future states without migrations.
- drive_secrets stores encrypted SA key JSON + nonce (AES-256-GCM).
"""
from datetime import datetime
from typing import Optional, final
from uuid import UUID as PyUUID

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


@final
class DriveConnection(Base, UUIDMixin, TimestampMixin):
    """Tracks which Google Shared Drives are connected per org."""

    __tablename__ = "drive_connections"

    org_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    library_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("libraries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    drive_id: Mapped[str] = mapped_column(String(128), nullable=False)
    drive_name: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="active"
    )  # active | paused | disconnected | error
    change_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_full_sync_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__: tuple[object, ...] = (
        UniqueConstraint("org_id", "drive_id", name="uq_drive_connections_org_drive"),
        Index("ix_drive_connections_status", "status"),
        {"comment": "Google Shared Drive connections per org"},
    )


@final
class DriveFile(Base, UUIDMixin, TimestampMixin):
    """Tracks every video file discovered in connected Shared Drives."""

    __tablename__ = "drive_files"

    org_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    connection_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("drive_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    google_file_id: Mapped[str] = mapped_column(String(256), nullable=False)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    md5_checksum: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    google_modified_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    google_created_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    drive_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    video_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )  # "gd_{sha256(org_id:google_file_id)[:16]}"
    processing_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending"
    )  # pending → downloading → transcoding → processing → indexing → indexed | failed | skipped
    proxy_s3_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    proxy_duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    proxy_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    thumbnail_s3_prefix: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scene_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- Enrichment tracking (V3b) ---
    enrichment_state: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )  # pending | running | done | failed_partial | failed
    stt_status: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )  # pending | running | done | failed
    ocr_status: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )  # pending | running | done | failed
    audio_s3_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    keyframe_s3_prefix: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    enrichment_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    enrichment_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- Caption enrichment ---
    caption_status: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )  # pending | running | done | failed
    caption_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    is_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__: tuple[object, ...] = (
        UniqueConstraint("org_id", "google_file_id", name="uq_drive_files_org_file"),
        Index("ix_drive_files_processing_status", "processing_status"),
        Index("ix_drive_files_enrichment_state", "enrichment_state"),
        {"comment": "Video files discovered in connected Google Shared Drives"},
    )


@final
class DriveSecret(Base, UUIDMixin, TimestampMixin):
    """Encrypted storage for Google service account keys (AES-256-GCM)."""

    __tablename__ = "drive_secrets"

    org_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    secret_type: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="service_account_key"
    )
    encrypted_value: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)  # 12-byte GCM nonce
    impersonate_email: Mapped[str] = mapped_column(String(320), nullable=False)

    __table_args__: tuple[object, ...] = (
        UniqueConstraint("org_id", "secret_type", name="uq_drive_secrets_org_type"),
        {"comment": "Encrypted Google SA keys for Drive integration"},
    )
