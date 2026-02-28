"""
Drive file discovery via internal HTTP API.

Claims connections from the API, lists files from Google Drive,
and upserts discovered files back to the API for processing.
No direct database access — all state managed via InternalAPIClient.
"""
# pyright: reportMissingImports=false
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build as build_google_service

from heimdex_worker_sdk.internal_api import InternalAPIClient

logger = logging.getLogger(__name__)

_MAX_UPSERT_BATCH = 500


def _build_drive_service(access_token: str):
    """Build a Google Drive API service from a pre-minted access token."""
    credentials = Credentials(token=access_token)
    return build_google_service("drive", "v3", credentials=credentials)


def discover_new_files(api_client: InternalAPIClient, settings: Any) -> int:
    """Discover new video files from claimed drive connections.

    Flow per connection:
    1. Claim connection (lease-based)
    2. Get short-lived Google access token via token broker
    3. List video files from Google Drive
    4. Upsert discovered files to API (batch, max 500 per call)
    5. Checkpoint connection (release lease)
    """
    connections = api_client.claim_connection(limit=5)
    if not connections:
        return 0

    discovered_count = 0

    for conn in connections:
        org_id_str = str(conn.org_id)
        try:
            token_info = api_client.get_drive_token(
                conn.connection_id, lease_token=conn.lease_token,
            )
            service = _build_drive_service(token_info.access_token)

            if conn.scope_type == "folder":
                count = _discover_folder_connection(
                    api_client, service, conn, settings,
                )
            else:
                count = _discover_drive_connection(
                    api_client, service, conn, settings,
                )
            discovered_count += count

            api_client.checkpoint(
                conn.connection_id,
                lease_token=conn.lease_token,
                release=True,
            )
            logger.info(
                "discover_connection_complete",
                extra={
                    "org_id": org_id_str,
                    "connection_id": str(conn.connection_id),
                    "scope_type": conn.scope_type,
                    "drive_id": conn.drive_id,
                    "folder_id": conn.folder_id,
                    "discovered": count,
                },
            )
        except Exception as e:
            logger.exception(
                "discover_connection_failed",
                extra={
                    "org_id": org_id_str,
                    "connection_id": str(conn.connection_id),
                    "scope_type": conn.scope_type,
                    "drive_id": conn.drive_id,
                    "folder_id": conn.folder_id,
                },
            )
            try:
                api_client.checkpoint(
                    conn.connection_id,
                    lease_token=conn.lease_token,
                    error_message=f"{type(e).__name__}: {e}",
                    release=True,
                )
            except Exception:
                logger.warning(
                    "discover_checkpoint_error_failed",
                    extra={"connection_id": str(conn.connection_id)},
                    exc_info=True,
                )

    return discovered_count


def _discover_drive_connection(
    api_client: InternalAPIClient,
    service: Any,
    conn: Any,
    settings: Any,
) -> int:
    """Discover files from a Shared Drive connection.

    Strategy:
    - If change_token exists AND last_full_sync_at < 7 days: incremental via changes().list()
    - Otherwise: full re-scan via files().list() + obtain initial change_token
    """
    now = datetime.now(timezone.utc)
    seven_days_ago = now - timedelta(days=7)

    last_full = None
    if conn.last_full_sync_at:
        try:
            last_full = datetime.fromisoformat(conn.last_full_sync_at)
        except (ValueError, TypeError):
            last_full = None

    use_incremental = (
        conn.change_token is not None
        and last_full is not None
        and last_full > seven_days_ago
    )

    if use_incremental:
        return _incremental_sync_drive(api_client, service, conn)

    count = _full_scan_drive(api_client, service, conn)
    start_token = service.changes().getStartPageToken(
        driveId=conn.drive_id, supportsAllDrives=True,
    ).execute()["startPageToken"]
    api_client.checkpoint(
        conn.connection_id,
        lease_token=conn.lease_token,
        change_token=start_token,
        last_full_sync_at=now.isoformat(),
        release=False,
    )
    return count


def _full_scan_drive(api_client: InternalAPIClient, service: Any, conn: Any) -> int:
    """Full file listing from Shared Drive (existing logic, extracted)."""
    items: list[dict[str, Any]] = []
    page_token: str | None = None

    while True:
        kwargs: dict[str, Any] = {
            "corpora": "drive",
            "driveId": conn.drive_id,
            "includeItemsFromAllDrives": True,
            "supportsAllDrives": True,
            "q": "mimeType contains 'video/' and trashed = false",
            "fields": "nextPageToken,files(id,name,mimeType,size,md5Checksum,modifiedTime,createdTime,parents,webViewLink)",
            "pageSize": 100,
        }
        if page_token:
            kwargs["pageToken"] = page_token

        response = service.files().list(**kwargs).execute()
        files = response.get("files", [])

        # Build path map for new files (resolve folder paths)
        path_map: dict[str, str] = {}
        if files:
            try:
                path_map = _resolve_folder_paths(service, files, conn.drive_id)
            except Exception:
                logger.warning(
                    "discover_path_resolve_failed",
                    extra={"org_id": str(conn.org_id), "file_count": len(files)},
                    exc_info=True,
                )

        for file in files:
            google_file_id = file.get("id")
            if not google_file_id:
                continue
            items.append(_file_to_upsert_item(file, path_map.get(google_file_id)))

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return _batch_upsert(api_client, conn, items)


def _incremental_sync_drive(api_client: InternalAPIClient, service: Any, conn: Any) -> int:
    """Incremental sync using changes().list() for a Shared Drive."""
    page_token = conn.change_token
    items_to_upsert: list[dict[str, Any]] = []
    file_ids_to_delete: list[str] = []

    while True:
        response = service.changes().list(
            pageToken=page_token,
            driveId=conn.drive_id,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            fields="nextPageToken,newStartPageToken,changes(fileId,removed,file(id,name,mimeType,size,md5Checksum,modifiedTime,trashed,parents,webViewLink))",
            spaces="drive",
        ).execute()

        for change in response.get("changes", []):
            file_id = change.get("fileId")
            is_removed = change.get("removed", False)
            file_data = change.get("file", {})
            is_trashed = file_data.get("trashed", False)

            if is_removed or is_trashed:
                if file_id:
                    file_ids_to_delete.append(file_id)
                continue

            mime_type = file_data.get("mimeType", "")
            if not mime_type.startswith("video/"):
                continue

            path_map: dict[str, str] = {}
            try:
                path_map = _resolve_folder_paths(service, [file_data], conn.drive_id)
            except Exception:
                logger.warning("incremental_path_resolve_failed", exc_info=True)

            drive_path = path_map.get(file_data.get("id"))
            items_to_upsert.append(_file_to_upsert_item(file_data, drive_path))

        if "newStartPageToken" in response:
            new_token = response["newStartPageToken"]
            break
        page_token = response["nextPageToken"]

    upsert_count = _batch_upsert(api_client, conn, items_to_upsert) if items_to_upsert else 0

    delete_count = 0
    if file_ids_to_delete:
        delete_count = _batch_delete(api_client, conn, file_ids_to_delete)

    api_client.checkpoint(
        conn.connection_id,
        lease_token=conn.lease_token,
        change_token=new_token,
        release=False,
    )

    logger.info(
        "incremental_sync_drive_complete",
        extra={
            "org_id": str(conn.org_id),
            "connection_id": str(conn.connection_id),
            "upserted": upsert_count,
            "deleted": delete_count,
            "changes_processed": len(items_to_upsert) + len(file_ids_to_delete),
        },
    )

    return upsert_count + delete_count


def _discover_folder_connection(
    api_client: InternalAPIClient,
    service: Any,
    conn: Any,
    settings: Any,
) -> int:
    """Discover video files from a folder-scoped OAuth connection (recursive)."""
    folder_id = conn.folder_id
    if not folder_id:
        logger.warning(
            "discover_folder_missing_folder_id",
            extra={"org_id": str(conn.org_id), "connection_id": str(conn.connection_id)},
        )
        return 0

    # Collect the root folder + all subfolder IDs for recursive scanning
    all_folder_ids = [folder_id]
    try:
        subfolder_ids = _list_subfolders(service, folder_id)
        all_folder_ids.extend(subfolder_ids)
    except Exception:
        logger.warning(
            "discover_subfolder_listing_failed",
            extra={"org_id": str(conn.org_id), "folder_id": folder_id},
            exc_info=True,
        )

    logger.info(
        "discover_folder_scan_start",
        extra={
            "org_id": str(conn.org_id),
            "connection_id": str(conn.connection_id),
            "root_folder_id": folder_id,
            "total_folders": len(all_folder_ids),
        },
    )

    folder_path_prefix = conn.folder_path or conn.folder_name or ""
    items: list[dict[str, Any]] = []

    for current_folder_id in all_folder_ids:
        page_token: str | None = None
        while True:
            kwargs: dict[str, Any] = {
                "q": f"'{current_folder_id}' in parents and mimeType contains 'video/' and trashed = false",
                "fields": "nextPageToken,files(id,name,mimeType,size,md5Checksum,modifiedTime,createdTime,parents,webViewLink)",
                "pageSize": 100,
            }
            if page_token:
                kwargs["pageToken"] = page_token

            response = service.files().list(**kwargs).execute()
            files = response.get("files", [])

            for file in files:
                google_file_id = file.get("id")
                if not google_file_id:
                    continue
                file_name = file.get("name", "")
                drive_path = f"{folder_path_prefix}/{file_name}" if folder_path_prefix else file_name
                items.append(_file_to_upsert_item(file, drive_path))

            page_token = response.get("nextPageToken")
            if not page_token:
                break

    return _batch_upsert(api_client, conn, items)


def _file_to_upsert_item(file: dict[str, Any], drive_path: str | None = None) -> dict[str, Any]:
    """Convert a Google Drive file dict to an upsert item dict."""
    raw_size = file.get("size", 0)
    try:
        size = int(raw_size) or None
    except (TypeError, ValueError):
        size = None

    item: dict[str, Any] = {
        "provider_file_id": file["id"],
        "name": file.get("name", ""),
        "mime_type": file.get("mimeType", "application/octet-stream"),
    }
    if size is not None:
        item["size"] = size
    md5 = file.get("md5Checksum")
    if md5:
        item["md5_checksum"] = md5
    modified_time = file.get("modifiedTime")
    if modified_time:
        item["modified_time"] = modified_time
    web_view_link = file.get("webViewLink")
    if web_view_link:
        item["web_view_link"] = web_view_link
    if drive_path:
        item["drive_path"] = drive_path

    return item


def _batch_upsert(
    api_client: InternalAPIClient,
    conn: Any,
    items: list[dict[str, Any]],
) -> int:
    """Upsert items in batches of _MAX_UPSERT_BATCH. Returns total created count."""
    if not items:
        return 0

    total_created = 0
    for i in range(0, len(items), _MAX_UPSERT_BATCH):
        batch = items[i : i + _MAX_UPSERT_BATCH]
        result = api_client.upsert_files(
            conn.connection_id,
            lease_token=conn.lease_token,
            items=batch,
        )
        total_created += result.created_count

    return total_created


def _batch_delete(api_client: InternalAPIClient, conn: Any, google_file_ids: list[str]) -> int:
    """Soft-delete files in batches."""
    total_deleted = 0
    for i in range(0, len(google_file_ids), _MAX_UPSERT_BATCH):
        batch = google_file_ids[i : i + _MAX_UPSERT_BATCH]
        result = api_client.delete_files(
            conn.connection_id,
            lease_token=conn.lease_token,
            google_file_ids=batch,
        )
        total_deleted += result.deleted_count
    return total_deleted


def _resolve_folder_paths(
    service: Any,
    files: list[dict[str, Any]],
    drive_id: str,
) -> dict[str, str]:
    """Resolve folder paths for a batch of files. Returns {file_id: path}."""
    parent_ids: set[str] = set()
    for f in files:
        parents = f.get("parents", [])
        for pid in parents:
            parent_ids.add(pid)

    if not parent_ids:
        return {}

    folder_names: dict[str, str] = {}
    for pid in parent_ids:
        try:
            folder = service.files().get(
                fileId=pid,
                supportsAllDrives=True,
                fields="id,name",
            ).execute()
            folder_names[pid] = folder.get("name", "")
        except Exception:
            pass

    result: dict[str, str] = {}
    for f in files:
        fid = f.get("id")
        if not fid:
            continue
        fname = f.get("name", "")
        parents = f.get("parents", [])
        if parents and parents[0] in folder_names:
            result[fid] = f"{folder_names[parents[0]]}/{fname}"
        else:
            result[fid] = fname

    return result


def _list_subfolders(service: Any, parent_id: str) -> list[str]:
    """Recursively list all subfolder IDs under a parent."""
    all_ids: list[str] = []
    queue = [parent_id]

    while queue:
        current = queue.pop(0)
        page_token: str | None = None
        while True:
            kwargs: dict[str, Any] = {
                "q": f"'{current}' in parents and mimeType='application/vnd.google-apps.folder' and trashed = false",
                "fields": "nextPageToken,files(id)",
                "pageSize": 1000,
            }
            if page_token:
                kwargs["pageToken"] = page_token

            response = service.files().list(**kwargs).execute()
            for folder in response.get("files", []):
                fid = folder.get("id")
                if fid:
                    all_ids.append(fid)
                    queue.append(fid)

            page_token = response.get("nextPageToken")
            if not page_token:
                break

    return all_ids
