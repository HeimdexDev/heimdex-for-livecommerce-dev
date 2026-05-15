"""
SQLAlchemy models for Google Drive integration.

Tables:
- drive_connections: Tracks connected Shared Drives and folder-scoped sources per org.
- drive_files: Tracks every video file discovered in connected Drive sources.
- drive_secrets: Encrypted storage for Drive credentials (AES-256-GCM).

Design decisions (from ARCHITECTURE.md):
- All tables FK to orgs.id with CASCADE delete (multi-tenant isolation).
- drive_files.video_id is deterministic: "gd_{sha256(org_id:google_file_id)[:16]}".
- processing_status is a text enum enforced at application layer (not DB CHECK)
  to allow future states without migrations.
- drive_secrets stores encrypted service account keys and OAuth token payloads.
"""
from datetime import datetime
from typing import Optional, final
from uuid import UUID as PyUUID

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


@final
class DriveConnection(Base, UUIDMixin, TimestampMixin):
    """Tracks which Google Drive scopes are connected per org."""

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
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False, server_default="drive")
    drive_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    drive_name: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    folder_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    folder_name: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    folder_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
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
    sync_requested_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # --- Lease tracking (connection-level, for sync claim) ---
    lease_token: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__: tuple[object, ...] = (
        Index(
            "uq_drive_connections_org_drive_not_null",
            "org_id",
            "drive_id",
            unique=True,
            postgresql_where=text("drive_id IS NOT NULL"),
        ),
        Index(
            "uq_drive_connections_org_folder_not_null",
            "org_id",
            "folder_id",
            unique=True,
            postgresql_where=text("folder_id IS NOT NULL"),
        ),
        Index("ix_drive_connections_status", "status"),
        {"comment": "Google Drive scoped connections per org"},
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
    web_view_link: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    video_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )  # "gd_{sha256(org_id:google_file_id)[:16]}"
    processing_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending"
    )  # pending → downloading → transcoding → processing → indexing → indexed | failed | skipped
    proxy_s3_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    proxy_duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    proxy_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    # --- Video metadata from ffprobe (export features) ---
    video_fps: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    video_width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    video_height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    original_s3_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    original_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
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
    # Image caption metadata (migration 046). Populated by
    # app.modules.image_caption.service after a successful OpenAI caption.
    # Used by the backfill CLI to target a specific prompt generation.
    caption_engine: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )
    caption_prompt_version: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    caption_generated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- Face enrichment ---
    face_status: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )  # pending | running | done | failed
    face_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # --- STT-then-split pipeline ---
    stt_result_s3_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stt_requested_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- Lease tracking (Internal API Hardening) ---
    lease_token: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(
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
    """Encrypted storage for Google service account keys and OAuth tokens (AES-256-GCM)."""

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
        {"comment": "Encrypted Google Drive credentials for Drive integration"},
    )


@final
class DriveWatchedFolder(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "drive_watched_folders"

    org_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    connection_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("drive_connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    google_folder_id: Mapped[str] = mapped_column(String(256), nullable=False)
    folder_name: Mapped[str] = mapped_column(String(500), nullable=False)
    folder_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parent_folder_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    sync_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    content_types: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)),
        nullable=False,
        server_default=text("ARRAY['video']::varchar[]"),
    )
    file_count_cached: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_enumerated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__: tuple[object, ...] = (
        UniqueConstraint("org_id", "google_folder_id", name="uq_watched_folders_org_folder"),
        Index("ix_watched_folders_org_id", "org_id"),
        Index("ix_watched_folders_connection_id", "connection_id"),
        Index(
            "ix_watched_folders_sync_enabled",
            "org_id",
            "sync_enabled",
            postgresql_where=text("sync_enabled = true"),
        ),
        Index("ix_watched_folders_parent", "org_id", "parent_folder_id"),
    )
