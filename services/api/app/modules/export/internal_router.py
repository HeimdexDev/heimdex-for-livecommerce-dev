"""Internal endpoints for the export worker.

These endpoints are called by the drive-worker (via HTTP + internal API key)
to fetch export records and update their status. No user auth required.
"""
import hmac
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status as http_status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db_session
from app.modules.export.repository import ExportRecordRepository

logger = logging.getLogger(__name__)


async def _verify_internal_token(
    authorization: str = Header(..., alias="Authorization"),
) -> str:
    settings = get_settings()
    if not settings.drive_internal_api_key:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Internal export API not configured",
        )
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header",
        )
    token = parts[1]
    if not hmac.compare_digest(token, settings.drive_internal_api_key):
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal token",
        )
    return token


router = APIRouter(
    prefix="/internal/export",
    tags=["internal-export"],
    dependencies=[Depends(_verify_internal_token)],
)


class ExportRecordResponse(BaseModel):
    id: str
    org_id: str
    user_id: str
    export_hash: str
    status: str
    sequence_name: str
    request_body: dict[str, Any]
    clip_count: int
    proxy_count: int
    s3_key: str | None = None
    expires_at: str


class UpdateExportStatusRequest(BaseModel):
    status: str = Field(..., pattern="^(generating|uploading|ready|failed)$")
    s3_key: str | None = None
    size_bytes: int | None = None
    error_message: str | None = None


@router.get("/{export_id}")
async def get_export_record(
    export_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> ExportRecordResponse:
    repo = ExportRecordRepository(db)
    record = await repo.get_by_id(export_id)
    if record is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Export record not found",
        )
    return ExportRecordResponse(
        id=str(record.id),
        org_id=str(record.org_id),
        user_id=str(record.user_id),
        export_hash=record.export_hash,
        status=record.status,
        sequence_name=record.sequence_name,
        request_body=record.request_body,
        clip_count=record.clip_count,
        proxy_count=record.proxy_count,
        s3_key=record.s3_key,
        expires_at=record.expires_at.isoformat(),
    )


@router.patch("/{export_id}/status")
async def update_export_status(
    export_id: UUID,
    body: UpdateExportStatusRequest,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    repo = ExportRecordRepository(db)
    record = await repo.get_by_id(export_id)
    if record is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Export record not found",
        )

    await repo.update_status(
        export_id,
        body.status,
        s3_key=body.s3_key,
        size_bytes=body.size_bytes,
        error_message=body.error_message,
    )

    logger.info(
        "export_status_updated",
        extra={
            "export_id": str(export_id),
            "new_status": body.status,
            "s3_key": body.s3_key,
        },
    )
    return {"status": "ok"}
