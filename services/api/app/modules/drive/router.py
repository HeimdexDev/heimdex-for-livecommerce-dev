from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import get_settings
from app.modules.drive.repository import DriveConnectionRepository, DriveFileRepository
from app.modules.drive.schemas import (
    DriveConnectionCreate,
    DriveConnectionResponse,
    DriveConnectionUpdate,
    DriveFileListResponse,
    DriveFileResponse,
)
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org

router = APIRouter(prefix="/drive", tags=["drive"])


def _require_drive_enabled() -> None:
    if not get_settings().drive_connector_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Drive connector is not enabled",
        )


@router.get("/connections", response_model=list[DriveConnectionResponse])
async def list_connections(
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    conn_repo: Annotated[DriveConnectionRepository, Depends()],
    _: Annotated[None, Depends(_require_drive_enabled)],
):
    return await conn_repo.list_by_org(org_ctx.org_id)


@router.post("/connections", response_model=DriveConnectionResponse, status_code=status.HTTP_201_CREATED)
async def create_connection(
    body: DriveConnectionCreate,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    conn_repo: Annotated[DriveConnectionRepository, Depends()],
    _: Annotated[None, Depends(_require_drive_enabled)],
):
    return await conn_repo.create(org_ctx.org_id, body)


@router.get("/connections/{connection_id}", response_model=DriveConnectionResponse)
async def get_connection(
    connection_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    conn_repo: Annotated[DriveConnectionRepository, Depends()],
    _: Annotated[None, Depends(_require_drive_enabled)],
):
    conn = await conn_repo.get_by_id(connection_id, org_ctx.org_id)
    if conn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    return conn


@router.patch("/connections/{connection_id}", response_model=DriveConnectionResponse)
async def update_connection(
    connection_id: UUID,
    body: DriveConnectionUpdate,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    conn_repo: Annotated[DriveConnectionRepository, Depends()],
    _: Annotated[None, Depends(_require_drive_enabled)],
):
    conn = await conn_repo.update(connection_id, org_ctx.org_id, body)
    if conn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    return conn


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    connection_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    conn_repo: Annotated[DriveConnectionRepository, Depends()],
    _: Annotated[None, Depends(_require_drive_enabled)],
):
    deleted = await conn_repo.delete(connection_id, org_ctx.org_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")


@router.get("/connections/{connection_id}/files", response_model=DriveFileListResponse)
async def list_files(
    connection_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    file_repo: Annotated[DriveFileRepository, Depends()],
    conn_repo: Annotated[DriveConnectionRepository, Depends()],
    _: Annotated[None, Depends(_require_drive_enabled)],
    processing_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    conn = await conn_repo.get_by_id(connection_id, org_ctx.org_id)
    if conn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    files, total = await file_repo.list_by_connection(
        connection_id, org_ctx.org_id, processing_status=processing_status, limit=limit, offset=offset
    )
    return DriveFileListResponse(
        files=[DriveFileResponse.model_validate(f) for f in files],
        total=total,
    )


@router.get("/files/{file_id}", response_model=DriveFileResponse)
async def get_file(
    file_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    file_repo: Annotated[DriveFileRepository, Depends()],
    _: Annotated[None, Depends(_require_drive_enabled)],
):
    f = await file_repo.get_by_id(file_id, org_ctx.org_id)
    if f is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return f
