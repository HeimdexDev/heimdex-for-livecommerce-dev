"""Business logic for the drive sync upsert path.

Extracted from ``internal_sync_router`` to:

- keep the HTTP handler thin and unit-testable in isolation (no FastAPI, no SQS);
- centralize the (create | revive | update | unchanged) decision tree;
- make soft-delete revive semantics explicit and covered by dedicated tests.

Revive: a previously soft-deleted ``drive_files`` row (``is_deleted=True``) that
Drive discovery has seen again. The unique constraint
``uq_drive_files_org_file`` spans ``(org_id, google_file_id)`` **without**
``is_deleted``, so the old row still owns the key. The service MUST reuse that
row, reset its pipeline state, and mark it for SQS reprocessing — otherwise
``db.add()`` would throw ``UniqueViolationError`` at flush and abort the whole
batch (observed incident: 2026-04 staging/prod discover outage).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.drive.internal_sync_schemas import DriveDiscoveredFile
from app.modules.drive.models import DriveConnection, DriveFile


def drive_video_id(org_id: str, google_file_id: str) -> str:
    """Deterministic video_id for Drive files.

    Canonical implementation: ``worker_sdk/drive_keys.py::drive_video_id``.
    Kept in sync — must produce identical output.
    """
    digest = hashlib.sha256(f"{org_id}:{google_file_id}".encode()).hexdigest()[:16]
    return f"gd_{digest}"


@dataclass
class UpsertOutcome:
    """Result of one ``DriveFileUpsertService.upsert_batch`` call.

    ``created`` / ``revived`` / ``modified_for_reprocess`` each become SQS
    processing jobs downstream. They are segregated so the router can emit
    distinct metrics and so tests can assert revive semantics separately from
    normal creation.

    ``updated_count`` includes metadata-only changes (e.g. rename) that do NOT
    trigger re-processing; this mirrors the prior inline behavior where a
    name-only change incremented ``updated_count`` but did not re-publish the
    processing SQS job.
    """

    created: list[DriveFile] = field(default_factory=list)
    revived: list[DriveFile] = field(default_factory=list)
    modified_for_reprocess: list[DriveFile] = field(default_factory=list)
    updated_count: int = 0
    unchanged_count: int = 0
    metadata_updates: list[dict[str, str]] = field(default_factory=list)

    @property
    def created_count(self) -> int:
        return len(self.created)

    @property
    def revived_count(self) -> int:
        return len(self.revived)

    @property
    def has_db_changes(self) -> bool:
        return bool(self.created or self.revived) or self.updated_count > 0


class DriveFileUpsertService:
    """Owns the (create | revive | update | unchanged) decision.

    No FastAPI, no HTTP, no SQS. Mutates the supplied ``AsyncSession`` but does
    NOT flush or commit — transaction control stays with the caller.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def upsert_batch(
        self,
        connection: DriveConnection,
        items: Sequence[DriveDiscoveredFile],
    ) -> UpsertOutcome:
        outcome = UpsertOutcome()
        if not items:
            return outcome

        org_id = connection.org_id
        org_id_str = str(org_id)

        provider_ids = [item.provider_file_id for item in items]

        # NOTE: ``is_deleted`` filter is DELIBERATELY absent here.
        # The unique constraint ``uq_drive_files_org_file`` does NOT include
        # ``is_deleted``, so soft-deleted rows still own their key. We must
        # find them here or a later ``db.add()`` collides at flush time and
        # aborts the entire batch (the 2026-04 discover outage root cause).
        existing_result = await self._db.execute(
            select(DriveFile).where(
                DriveFile.org_id == org_id,
                DriveFile.google_file_id.in_(provider_ids),
            )
        )
        existing_files_map: dict[str, DriveFile] = {
            f.google_file_id: f for f in existing_result.scalars().all()
        }

        seen_in_batch: set[str] = set()

        for item in items:
            if item.provider_file_id in seen_in_batch:
                outcome.unchanged_count += 1
                continue
            seen_in_batch.add(item.provider_file_id)

            existing_file = existing_files_map.get(item.provider_file_id)

            if existing_file is None:
                outcome.created.append(
                    self._create_new(connection, item, org_id_str)
                )
                continue

            if existing_file.is_deleted:
                self._revive(existing_file, item)
                outcome.revived.append(existing_file)
                continue

            self._update_existing(existing_file, item, outcome)

        return outcome

    def _create_new(
        self,
        connection: DriveConnection,
        item: DriveDiscoveredFile,
        org_id_str: str,
    ) -> DriveFile:
        video_id = drive_video_id(org_id_str, item.provider_file_id)
        drive_file = DriveFile(
            org_id=connection.org_id,
            connection_id=connection.id,
            google_file_id=item.provider_file_id,
            file_name=item.name,
            mime_type=item.mime_type,
            file_size_bytes=item.size,
            md5_checksum=item.md5_checksum,
            google_modified_time=item.modified_time,
            google_created_time=item.created_time,
            drive_path=item.drive_path,
            web_view_link=item.web_view_link,
            video_id=video_id,
            processing_status="pending",
            enrichment_state="pending",
            stt_status="pending",
            ocr_status="pending",
        )
        self._db.add(drive_file)
        return drive_file

    def _revive(self, existing: DriveFile, item: DriveDiscoveredFile) -> None:
        """Resurrect a soft-deleted row as fresh pipeline work.

        The row keeps its ``id`` and ``video_id`` (both deterministic /
        stable so any lingering foreign references remain valid). All
        pipeline-state columns are reset to mirror a brand-new file.
        """
        existing.is_deleted = False
        existing.deleted_at = None
        existing.processing_status = "pending"
        existing.enrichment_state = "pending"
        existing.stt_status = "pending"
        existing.ocr_status = "pending"
        # caption_status / face_status: NULL on creation by _create_new, so
        # revive clears them too (not "pending") to match the create path.
        existing.caption_status = None
        existing.face_status = None
        existing.proxy_s3_key = None
        existing.original_s3_key = None
        existing.audio_s3_key = None
        existing.keyframe_s3_prefix = None
        existing.thumbnail_s3_prefix = None
        existing.scene_count = 0
        existing.retry_count = 0
        existing.last_error = None
        existing.enrichment_error = None
        existing.caption_error = None
        existing.face_error = None

        # Refresh metadata from the discovery item.
        existing.file_name = item.name
        existing.mime_type = item.mime_type
        existing.file_size_bytes = item.size
        existing.md5_checksum = item.md5_checksum
        existing.google_modified_time = item.modified_time
        if item.created_time and existing.google_created_time is None:
            existing.google_created_time = item.created_time
        existing.drive_path = item.drive_path
        existing.web_view_link = item.web_view_link

    def _update_existing(
        self,
        existing_file: DriveFile,
        item: DriveDiscoveredFile,
        outcome: UpsertOutcome,
    ) -> None:
        changes_made = False

        if (
            item.md5_checksum
            and existing_file.md5_checksum
            and item.md5_checksum != existing_file.md5_checksum
        ):
            existing_file.md5_checksum = item.md5_checksum
            existing_file.file_size_bytes = item.size
            existing_file.google_modified_time = item.modified_time
            existing_file.processing_status = "pending"
            existing_file.enrichment_state = "pending"
            existing_file.stt_status = "pending"
            existing_file.ocr_status = "pending"
            existing_file.caption_status = "pending"
            existing_file.face_status = "pending"
            existing_file.proxy_s3_key = None
            existing_file.scene_count = 0
            existing_file.retry_count = 0
            existing_file.last_error = None
            outcome.modified_for_reprocess.append(existing_file)
            changes_made = True

        if item.name != existing_file.file_name:
            existing_file.file_name = item.name
            outcome.metadata_updates.append(
                {"video_id": existing_file.video_id, "video_title": item.name}
            )
            changes_made = True

        if item.drive_path and item.drive_path != existing_file.drive_path:
            existing_file.drive_path = item.drive_path
            outcome.metadata_updates.append(
                {"video_id": existing_file.video_id, "source_path": item.drive_path}
            )
            changes_made = True

        if (
            item.web_view_link
            and item.web_view_link != existing_file.web_view_link
        ):
            existing_file.web_view_link = item.web_view_link
            changes_made = True

        # Backfill google_created_time if not yet set (write-once).
        if item.created_time and existing_file.google_created_time is None:
            existing_file.google_created_time = item.created_time
            changes_made = True

        if changes_made:
            outcome.updated_count += 1
        else:
            outcome.unchanged_count += 1
