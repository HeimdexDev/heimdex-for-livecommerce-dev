"""Blur layer export service.

One-shot composition of a parent :class:`BlurJob`'s per-category FFV1
masks into a single NLE-compatible ProRes 4444 ``.mov`` layer. The
customer picks which categories to include; a dedupe window collapses
duplicate button-mashes to the same job row.

Loose coupling: this service depends on :class:`BlurJobRepository` for
parent-job validation and :class:`BlurExportRepository` for row-level
CRUD, but nothing from the worker side. All worker interaction goes
through the SQS producer + the internal callback endpoints.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import cast
from uuid import UUID

from fastapi import HTTPException, status

from app.config import get_settings
from app.logging_config import get_logger
from app.modules.blur.export_repository import BlurExportRepository
from app.modules.blur.models import (
    BLUR_STATUS_DONE,
    BLUR_STATUS_FAILED,
    BlurExport,
    BlurJob,
)
from app.modules.blur.repository import BlurJobRepository
from app.modules.blur.schemas import (
    BlurExportResponse,
    CreateBlurExportRequest,
)

logger = get_logger(__name__)


# Double-click debounce window — matches the parent blur job service.
_DEDUPE_WINDOW_SECONDS = 30

# Presigned URL lifetime for layer downloads. Short by design — the
# frontend re-fetches on every "Download" click anyway, and a short
# lifetime limits how long a leaked URL is valid.
_DOWNLOAD_URL_TTL_SECONDS = 600  # 10 minutes


def compute_export_hash(categories: tuple[str, ...], export_format: str) -> str:
    """Deterministic sha256 of an export's category set + format.

    Sort the categories first so ``("face","logo")`` and
    ``("logo","face")`` collapse to the same row. The parent job hash
    covers the blur options that produced the masks; this hash is only
    about which masks to combine at export time.
    """
    canonical = json.dumps(
        {"categories": sorted(categories), "format": export_format},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _to_response(row: BlurExport, *, download_url: str | None = None) -> BlurExportResponse:
    return BlurExportResponse(
        id=cast(UUID, row.id),
        blur_job_id=row.blur_job_id,
        file_id=row.file_id,
        video_id=row.video_id,
        requested_by=row.requested_by,
        status=row.status,
        categories=list(row.categories or []),
        format=row.format,
        layer_s3_key=row.layer_s3_key,
        error=row.error,
        requested_at=row.requested_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
        download_url=download_url,
    )


class BlurExportService:
    """Orchestrates create / read / download-URL for blur layer exports.

    Does NOT touch S3 delete logic — export artifacts have a short S3
    lifecycle (7 days) and are best reaped automatically. Cancel on a
    running export is intentionally not supported in v1; worker jobs
    run to completion.
    """

    def __init__(
        self,
        repository: BlurExportRepository,
        blur_job_repository: BlurJobRepository,
    ) -> None:
        self.repository = repository
        self.blur_job_repository = blur_job_repository

    # ---------- public ----------

    async def create_export(
        self,
        *,
        org_id: UUID,
        user_id: UUID,
        blur_job_id: UUID,
        payload: CreateBlurExportRequest,
    ) -> BlurExportResponse:
        settings = get_settings()
        if not settings.blur_enabled:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Blur feature is disabled",
            )
        if not settings.blur_export_enabled:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Blur layer export is disabled",
            )

        # 1. Parent job must exist, belong to this org, be done, and
        #    have mask keys populated. Without masks there's nothing to
        #    composite.
        parent = await self.blur_job_repository.get_by_id(org_id, blur_job_id)
        if parent is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Parent blur job not found",
            )
        if parent.status != BLUR_STATUS_DONE:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Parent blur job is in status={parent.status!r}, "
                    f"expected {BLUR_STATUS_DONE!r}"
                ),
            )
        if not parent.mask_s3_keys:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Parent blur job has no per-category mask layers. "
                    "Re-run blur to generate exportable layers."
                ),
            )

        # 2. All requested categories must exist on the parent. A
        #    typo or UI drift surfaces as a clean 409 rather than a
        #    silent worker failure.
        missing = [c for c in payload.categories if c not in parent.mask_s3_keys]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Categories not available on parent job: {sorted(missing)}. "
                    f"Available: {sorted(parent.mask_s3_keys.keys())}"
                ),
            )

        # 3. Concurrency cap — reuses the blur job cap since the
        #    underlying GPU box is the same Aircloud container.
        active_count = await self.repository.count_active_for_org(org_id)
        if active_count >= settings.blur_max_active_per_org:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Too many active blur exports for org "
                    f"({active_count}/{settings.blur_max_active_per_org}). "
                    f"Wait for existing exports to finish."
                ),
            )

        # 4. Dedupe on (parent, category set, format) — customers
        #    clicking Export twice should see the same row, not two.
        categories_hash = compute_export_hash(payload.categories, payload.format)
        dedupe_since = datetime.now(timezone.utc) - timedelta(seconds=_DEDUPE_WINDOW_SECONDS)
        existing = await self.repository.find_recent_duplicate(
            blur_job_id=blur_job_id,
            categories_hash=categories_hash,
            format_=payload.format,
            since=dedupe_since,
        )
        if existing is not None:
            logger.info(
                "blur_export_idempotent_replay",
                export_id=str(existing.id),
                blur_job_id=str(blur_job_id),
                org_id=str(org_id),
                categories_hash=categories_hash,
            )
            return _to_response(existing)

        # 5. Create row. ``categories`` is stored as a JSONB list so
        #    worker / future analytics queries don't need to parse the
        #    hash to recover it.
        row = await self.repository.create(
            org_id=org_id,
            blur_job_id=blur_job_id,
            file_id=parent.file_id,
            video_id=parent.video_id,
            requested_by=user_id,
            categories=sorted(payload.categories),
            categories_hash=categories_hash,
            format_=payload.format,
        )

        logger.info(
            "blur_export_created",
            export_id=str(row.id),
            blur_job_id=str(blur_job_id),
            org_id=str(org_id),
            user_id=str(user_id),
            categories=list(payload.categories),
            format=payload.format,
            categories_hash=categories_hash,
        )

        # 6. Publish to SQS. Fire-and-forget with a failure fallback
        #    identical to the blur job path — if publish fails, mark
        #    the row failed so the user isn't stuck on "queued" forever.
        try:
            from app.sqs_producer import publish_blur_export

            # Filter mask keys to the requested subset so the worker
            # never sees categories it didn't ask for.
            selected_masks = {
                c: parent.mask_s3_keys[c]
                for c in payload.categories
                if c in parent.mask_s3_keys
            }
            publish_blur_export(
                export_id=cast(UUID, row.id),
                blur_job_id=blur_job_id,
                file_id=parent.file_id,
                org_id=org_id,
                video_id=parent.video_id,
                source_s3_key=parent.source_s3_key,
                mask_s3_keys=selected_masks,
                categories=list(payload.categories),
                export_format=payload.format,
            )
        except Exception:
            logger.exception("sqs_blur_export_publish_failed", export_id=str(row.id))
            from sqlalchemy import update

            await self.repository.session.execute(
                update(BlurExport)
                .where(BlurExport.id == row.id)
                .values(
                    status=BLUR_STATUS_FAILED,
                    error="Failed to enqueue blur export",
                    completed_at=datetime.now(timezone.utc),
                )
            )
            await self.repository.session.flush()
            row.status = BLUR_STATUS_FAILED
            row.error = "Failed to enqueue blur export"

        return _to_response(row)

    async def get_export(
        self,
        *,
        org_id: UUID,
        export_id: UUID,
    ) -> BlurExportResponse:
        row = await self.repository.get_by_id(org_id, export_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Blur export not found",
            )
        download_url = await self._maybe_download_url(row)
        return _to_response(row, download_url=download_url)

    async def generate_download_url(
        self,
        *,
        org_id: UUID,
        export_id: UUID,
    ) -> str:
        """Return a fresh presigned URL to the exported ``.mov``.

        Only valid for ``status=done``; 404 otherwise so the frontend
        can distinguish "not ready yet" from "real not found".
        """
        row = await self.repository.get_by_id(org_id, export_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Blur export not found",
            )
        if row.status != BLUR_STATUS_DONE or not row.layer_s3_key:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Blur export is not ready (status={row.status!r})",
            )
        url = await self._presigned_get(row.layer_s3_key)
        if url is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to generate download URL",
            )
        return url

    # ---------- internals ----------

    async def _maybe_download_url(self, row: BlurExport) -> str | None:
        if row.status != BLUR_STATUS_DONE or not row.layer_s3_key:
            return None
        return await self._presigned_get(row.layer_s3_key)

    async def _presigned_get(self, s3_key: str) -> str | None:
        """Wrap ``S3Client.generate_presigned_url_async`` so the service
        never takes a direct boto3 dependency at import time.
        """
        try:
            from app.storage.s3 import S3Client

            settings = get_settings()
            s3 = S3Client(bucket=settings.drive_s3_bucket)
            return await s3.generate_presigned_url_async(
                s3_key, expires_in=_DOWNLOAD_URL_TTL_SECONDS,
            )
        except Exception:
            logger.exception("blur_export_presign_failed", s3_key=s3_key)
            return None
