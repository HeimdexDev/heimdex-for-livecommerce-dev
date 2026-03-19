import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import get_settings
from app.dependencies import (
    get_drive_connection_repository,
    get_drive_file_repository,
    get_drive_secret_repository,
    get_scene_opensearch_client,
    get_watched_folder_repository,
)
from app.modules.drive.google_client import DriveClient
from app.modules.drive.models import DriveConnection
from app.modules.drive.repository import (
    DriveConnectionRepository,
    DriveFileRepository,
    DriveSecretRepository,
)
from app.modules.drive.router import _decrypt_oauth_token_data, _require_drive_enabled
from app.modules.drive.watched_folder_repository import WatchedFolderInput, WatchedFolderRepository
from app.modules.drive.watched_folder_schemas import (
    DriveInfoResponse,
    FolderTreeResponse,
    ToggleFolderResponse,
    WatchedFolderContentTypesRequest,
    WatchedFolderResponse,
    WatchedFolderToggleRequest,
)
from app.modules.search.scene_client import SceneSearchClient
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/drive/watched-folders", tags=["watched-folders"])


def _build_folder_inputs(folders: list[dict[str, Any]]) -> list[WatchedFolderInput]:
    by_id = {str(f["id"]): f for f in folders if f.get("id")}
    path_cache: dict[str, str] = {}

    def _resolve_path(folder_id: str) -> str:
        cached = path_cache.get(folder_id)
        if cached is not None:
            return cached

        folder = by_id.get(folder_id)
        if folder is None:
            return ""

        name = str(folder.get("name") or folder_id)
        parents = folder.get("parents") or []
        parent_id = str(parents[0]) if parents else None

        if parent_id and parent_id in by_id:
            parent_path = _resolve_path(parent_id)
            resolved = f"{parent_path}/{name}" if parent_path else f"/{name}"
        else:
            resolved = f"/{name}"

        path_cache[folder_id] = resolved
        return resolved

    inputs: list[WatchedFolderInput] = []
    for folder in folders:
        folder_id = str(folder.get("id") or "")
        if not folder_id:
            continue

        parents = folder.get("parents") or []
        parent_id = str(parents[0]) if parents else None
        if parent_id and parent_id not in by_id:
            parent_id = None

        inputs.append(
            {
                "google_folder_id": folder_id,
                "folder_name": str(folder.get("name") or folder_id),
                "folder_path": _resolve_path(folder_id),
                "parent_folder_id": parent_id,
            }
        )

    return inputs


def _build_drive_infos(connections: list[DriveConnection]) -> list[DriveInfoResponse]:
    return [
        DriveInfoResponse(
            connection_id=conn.id,
            drive_id=conn.drive_id,
            drive_name=conn.drive_name,
            scope_type=conn.scope_type,
        )
        for conn in connections
        if conn.scope_type in {"my_drive", "shared_drive"}
    ]


@router.post("/enumerate-folders", response_model=FolderTreeResponse)
async def enumerate_folders(
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    conn_repo: Annotated[DriveConnectionRepository, Depends(get_drive_connection_repository)],
    folder_repo: Annotated[WatchedFolderRepository, Depends(get_watched_folder_repository)],
    secret_repo: Annotated[DriveSecretRepository, Depends(get_drive_secret_repository)],
    _: Annotated[None, Depends(_require_drive_enabled)],
):
    settings = get_settings()
    secret = await secret_repo.get_by_org(org_ctx.org_id, secret_type="oauth_token")
    if secret is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google Drive is not connected. Please connect via OAuth first.",
        )

    token_data = _decrypt_oauth_token_data(secret, settings.drive_sa_encryption_key)
    drive_client = DriveClient.from_oauth_token(
        refresh_token=token_data["refresh_token"],
        client_id=token_data["client_id"],
        client_secret=token_data["client_secret"],
    )

    shared_drives = drive_client.list_shared_drives()
    connections = await conn_repo.list_by_org(org_ctx.org_id)
    library_id = connections[0].library_id if connections else None
    if library_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No library found. Please connect Google Drive first.",
        )

    my_drive_conn = next((c for c in connections if c.scope_type == "my_drive"), None)
    if my_drive_conn is None:
        my_drive_conn = DriveConnection(
            org_id=org_ctx.org_id,
            library_id=library_id,
            scope_type="my_drive",
            drive_id=None,
            drive_name="My Drive",
        )
        conn_repo.session.add(my_drive_conn)
        await conn_repo.session.flush()
        connections.append(my_drive_conn)

    my_drive_folders = drive_client.list_all_folders(None)
    my_drive_inputs = _build_folder_inputs(my_drive_folders)
    await folder_repo.bulk_upsert(org_ctx.org_id, my_drive_conn.id, my_drive_inputs)

    for shared_drive in shared_drives:
        drive_id = str(shared_drive.get("id") or "")
        if not drive_id:
            continue

        drive_name = str(shared_drive.get("name") or drive_id)
        shared_conn = next(
            (
                c
                for c in connections
                if c.scope_type == "shared_drive" and c.drive_id == drive_id
            ),
            None,
        )
        if shared_conn is None:
            shared_conn = DriveConnection(
                org_id=org_ctx.org_id,
                library_id=library_id,
                scope_type="shared_drive",
                drive_id=drive_id,
                drive_name=drive_name,
            )
            conn_repo.session.add(shared_conn)
            await conn_repo.session.flush()
            connections.append(shared_conn)

        folders = drive_client.list_all_folders(drive_id)
        inputs = _build_folder_inputs(folders)
        await folder_repo.bulk_upsert(org_ctx.org_id, shared_conn.id, inputs)

    folders = await folder_repo.list_by_org(org_ctx.org_id)
    return FolderTreeResponse(
        folders=[WatchedFolderResponse.model_validate(folder) for folder in folders],
        drives=_build_drive_infos(connections),
    )


@router.get("", response_model=FolderTreeResponse)
async def get_watched_folders(
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    conn_repo: Annotated[DriveConnectionRepository, Depends(get_drive_connection_repository)],
    folder_repo: Annotated[WatchedFolderRepository, Depends(get_watched_folder_repository)],
    _: Annotated[None, Depends(_require_drive_enabled)],
):
    connections = await conn_repo.list_by_org(org_ctx.org_id)
    folders = await folder_repo.list_by_org(org_ctx.org_id)
    return FolderTreeResponse(
        folders=[WatchedFolderResponse.model_validate(folder) for folder in folders],
        drives=_build_drive_infos(connections),
    )


@router.patch("/{folder_id}/toggle", response_model=ToggleFolderResponse)
async def toggle_folder_sync(
    folder_id: UUID,
    body: WatchedFolderToggleRequest,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    folder_repo: Annotated[WatchedFolderRepository, Depends(get_watched_folder_repository)],
    conn_repo: Annotated[DriveConnectionRepository, Depends(get_drive_connection_repository)],
    file_repo: Annotated[DriveFileRepository, Depends(get_drive_file_repository)],
    scene_client: Annotated[SceneSearchClient, Depends(get_scene_opensearch_client)],
    _: Annotated[None, Depends(_require_drive_enabled)],
):
    folder = await folder_repo.update_toggle(folder_id, org_ctx.org_id, body.sync_enabled)
    if folder is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")

    deleted_file_count = 0
    if body.sync_enabled:
        await conn_repo.set_sync_requested(folder.connection_id, org_ctx.org_id)
    else:
        video_ids = await file_repo.soft_delete_by_watched_folder(org_ctx.org_id, folder.google_folder_id)
        deleted_file_count = len(video_ids)
        for vid in video_ids:
            try:
                await scene_client.delete_scenes_by_video_id(str(org_ctx.org_id), vid)
            except Exception:
                logger.warning(
                    "watched_folder_scene_delete_failed",
                    extra={
                        "org_id": str(org_ctx.org_id),
                        "folder_id": str(folder_id),
                        "video_id": vid,
                    },
                )

    return ToggleFolderResponse(
        folder=WatchedFolderResponse.model_validate(folder),
        deleted_file_count=deleted_file_count,
    )


@router.patch("/{folder_id}/content-types", response_model=WatchedFolderResponse)
async def update_content_types(
    folder_id: UUID,
    body: WatchedFolderContentTypesRequest,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    folder_repo: Annotated[WatchedFolderRepository, Depends(get_watched_folder_repository)],
    _: Annotated[None, Depends(_require_drive_enabled)],
):
    content_types = [value for value in body.content_types]
    folder = await folder_repo.update_content_types(folder_id, org_ctx.org_id, content_types)
    if folder is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")
    return WatchedFolderResponse.model_validate(folder)
