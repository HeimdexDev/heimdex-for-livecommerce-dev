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
from googleapiclient.errors import HttpError

from heimdex_worker_sdk.content_type import IMAGE_MIME_TYPES, is_image, is_supported_mime
from heimdex_worker_sdk.internal_api import InternalAPIClient

# Build the Drive API mimeType filter from the canonical set
_IMAGE_MIME_FILTER = " or ".join(f"mimeType='{m}'" for m in sorted(IMAGE_MIME_TYPES))
_MIME_QUERY = f"(mimeType contains 'video/' or {_IMAGE_MIME_FILTER})"

logger = logging.getLogger(__name__)

_MAX_UPSERT_BATCH = 500


def _should_ingest_file(
    file_data: dict[str, Any],
    watched_folder_ids: set[str],
    content_types_map: dict[str, list[str]],
) -> bool:
    """Check if a file should be ingested based on watched folder settings."""
    parents = file_data.get("parents") or []
    if not parents:
        return False

    parent_id = parents[0]
    if parent_id not in watched_folder_ids:
        return False

    mime_type = file_data.get("mimeType", "")
    allowed_types = content_types_map.get(parent_id, ["video"])

    if "video" in allowed_types and mime_type.startswith("video/"):
        return True
    if "image" in allowed_types and _is_image_mime(mime_type):
        return True

    return False


def _is_image_mime(mime_type: str) -> bool:
    """Check if MIME type is a supported image type."""
    return is_image(mime_type)


def _expand_watched_folder_ids(
    service: Any,
    watched: list[dict[str, Any]],
) -> tuple[set[str], dict[str, list[str]]]:
    """Expand watched folders to include all nested subfolder IDs.

    For each watched folder, recursively lists subfolders via the Google
    Drive API and adds them to the watched set.  Subfolders inherit the
    content_types of their watched ancestor.

    Returns:
        (watched_folder_ids, content_types_map) with subfolders included.
    """
    watched_folder_ids: set[str] = set()
    content_types_map: dict[str, list[str]] = {}

    for w in watched:
        folder_id = w["google_folder_id"]
        content_types = w.get("content_types", ["video"])

        watched_folder_ids.add(folder_id)
        content_types_map[folder_id] = content_types

        try:
            subfolder_ids = _list_subfolders(service, folder_id)
            for sub_id in subfolder_ids:
                watched_folder_ids.add(sub_id)
                content_types_map[sub_id] = content_types
        except Exception:
            logger.warning(
                "watched_folder_subfolder_expansion_failed",
                extra={"google_folder_id": folder_id},
                exc_info=True,
            )

    return watched_folder_ids, content_types_map


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

    # Watched folder filtering — only active when folder_sync_v2_enabled
    watched_folder_ids: set[str] = set()
    content_types_map: dict[str, list[str]] = {}

    if getattr(settings, "folder_sync_v2_enabled", False):
        watched = api_client.get_watched_folders(str(conn.connection_id))
        if not watched:
            logger.info(
                "discover_skip_no_watched_folders",
                extra={"connection_id": str(conn.connection_id)},
            )
            return 0
        watched_folder_ids, content_types_map = _expand_watched_folder_ids(
            service, watched,
        )
        logger.info(
            "watched_folder_expansion_complete",
            extra={
                "connection_id": str(conn.connection_id),
                "watched_top_level": len(watched),
                "watched_total": len(watched_folder_ids),
            },
        )

    # TODO(folder-sync): Add _post_process_check() to process.py.
    # When a file completes processing, check if its parent folder is still enabled.
    # If not, soft-delete the file and skip enrichment publishing.
    # This handles the race condition where a folder is toggled OFF while a file
    # is mid-processing (downloading/transcoding/enriching).

    if use_incremental:
        return _incremental_sync_drive(
            api_client,
            service,
            conn,
            watched_folder_ids,
            content_types_map,
        )

    count = _full_scan_drive(
        api_client,
        service,
        conn,
        watched_folder_ids,
        content_types_map,
    )
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


def _full_scan_drive(
    api_client: InternalAPIClient,
    service: Any,
    conn: Any,
    watched_folder_ids: set[str],
    content_types_map: dict[str, list[str]],
) -> int:
    """Full file listing from Shared Drive (existing logic, extracted)."""
    items: list[dict[str, Any]] = []
    scanned_google_file_ids: set[str] = set()
    page_token: str | None = None

    while True:
        kwargs: dict[str, Any] = {
            "corpora": "drive",
            "driveId": conn.drive_id,
            "includeItemsFromAllDrives": True,
            "supportsAllDrives": True,
            "q": f"{_MIME_QUERY} and trashed = false",
            "fields": "nextPageToken,files(id,name,mimeType,size,md5Checksum,modifiedTime,createdTime,parents,webViewLink)",
            "pageSize": 100,
        }
        if page_token:
            kwargs["pageToken"] = page_token

        response = service.files().list(**kwargs).execute()
        files = response.get("files", [])

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

        if watched_folder_ids:
            filtered_files = [
                f for f in files
                if _should_ingest_file(f, watched_folder_ids, content_types_map)
            ]
        else:
            filtered_files = files

        for file in filtered_files:
            google_file_id = file.get("id")
            if not google_file_id:
                continue
            scanned_google_file_ids.add(google_file_id)
            items.append(_file_to_upsert_item(file, path_map.get(google_file_id)))

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    upsert_count, metadata_updates = _batch_upsert(api_client, conn, items)
    if metadata_updates:
        api_client.update_metadata(
            conn.connection_id,
            lease_token=conn.lease_token,
            updates=metadata_updates,
        )

    reconcile_count = _reconcile_deleted_files(api_client, conn, scanned_google_file_ids)
    return upsert_count + reconcile_count


def _incremental_sync_drive(
    api_client: InternalAPIClient,
    service: Any,
    conn: Any,
    watched_folder_ids: set[str],
    content_types_map: dict[str, list[str]],
) -> int:
    """Incremental sync using changes().list() for a Shared Drive."""
    page_token = conn.change_token
    items_to_upsert: list[dict[str, Any]] = []
    file_ids_to_delete: set[str] = set()
    existing_file_ids = api_client.list_connection_file_ids(conn.connection_id)

    while True:
        response = service.changes().list(
            pageToken=page_token,
            driveId=conn.drive_id,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            fields="nextPageToken,newStartPageToken,changes(fileId,removed,file(id,name,mimeType,size,md5Checksum,modifiedTime,createdTime,trashed,parents,webViewLink))",
            spaces="drive",
        ).execute()

        for change in response.get("changes", []):
            file_id = change.get("fileId")
            is_removed = change.get("removed", False)
            file_data = change.get("file", {})
            is_trashed = file_data.get("trashed", False)

            if is_removed or is_trashed:
                if file_id:
                    file_ids_to_delete.add(file_id)
                continue

            mime_type = file_data.get("mimeType", "")
            if not is_supported_mime(mime_type):
                continue

            if watched_folder_ids and not _should_ingest_file(file_data, watched_folder_ids, content_types_map):
                google_file_id = file_data.get("id")
                if google_file_id and google_file_id in existing_file_ids:
                    file_ids_to_delete.add(google_file_id)
                    logger.info(
                        "file_moved_out_of_watched_folder",
                        extra={
                            "google_file_id": google_file_id,
                            "parents": file_data.get("parents"),
                        },
                    )
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

    upsert_count = 0
    if items_to_upsert:
        upsert_count, metadata_updates = _batch_upsert(api_client, conn, items_to_upsert)
        if metadata_updates:
            api_client.update_metadata(
                conn.connection_id,
                lease_token=conn.lease_token,
                updates=metadata_updates,
            )

    delete_count = 0
    if file_ids_to_delete:
        delete_count = _batch_delete(api_client, conn, list(file_ids_to_delete))

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
    now = datetime.now(timezone.utc)
    seven_days_ago = now - timedelta(days=7)

    # Lazy backfill: detect drive_id for pre-Phase-5 folder connections
    detected_drive_id: str | None = None
    if conn.drive_id is None and conn.folder_id:
        try:
            file_meta = service.files().get(
                fileId=conn.folder_id,
                fields="driveId",
                supportsAllDrives=True,
            ).execute()
            detected_drive_id = file_meta.get("driveId")
            if detected_drive_id:
                conn.drive_id = detected_drive_id
                logger.info(
                    "folder_drive_id_backfilled",
                    extra={
                        "org_id": str(conn.org_id),
                        "connection_id": str(conn.connection_id),
                        "folder_id": conn.folder_id,
                        "drive_id": detected_drive_id,
                    },
                )
        except Exception:
            logger.warning(
                "folder_drive_id_detection_failed",
                extra={
                    "org_id": str(conn.org_id),
                    "connection_id": str(conn.connection_id),
                    "folder_id": conn.folder_id,
                },
                exc_info=True,
            )

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
        try:
            return _incremental_sync_folder(api_client, service, conn, detected_drive_id=detected_drive_id)
        except HttpError as e:
            if getattr(e.resp, "status", None) == 410:
                logger.warning(
                    "folder_change_token_expired",
                    extra={
                        "org_id": str(conn.org_id),
                        "connection_id": str(conn.connection_id),
                        "folder_id": conn.folder_id,
                    },
                )
            else:
                raise

    count = _full_scan_folder(api_client, service, conn)

    token_kwargs: dict[str, Any] = {"supportsAllDrives": True}
    if conn.drive_id:
        token_kwargs["driveId"] = conn.drive_id
    start_token = service.changes().getStartPageToken(**token_kwargs).execute()["startPageToken"]

    api_client.checkpoint(
        conn.connection_id,
        lease_token=conn.lease_token,
        change_token=start_token,
        last_full_sync_at=now.isoformat(),
        drive_id=detected_drive_id,
        release=False,
    )
    return count


def _full_scan_folder(api_client: InternalAPIClient, service: Any, conn: Any) -> int:
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
    scanned_google_file_ids: set[str] = set()

    for current_folder_id in all_folder_ids:
        page_token: str | None = None
        while True:
            kwargs: dict[str, Any] = {
                "q": f"'{current_folder_id}' in parents and {_MIME_QUERY} and trashed = false",
                "fields": "nextPageToken,files(id,name,mimeType,size,md5Checksum,modifiedTime,createdTime,parents,webViewLink)",
                "pageSize": 100,
                "supportsAllDrives": True,
                "includeItemsFromAllDrives": True,
            }
            if page_token:
                kwargs["pageToken"] = page_token

            response = service.files().list(**kwargs).execute()
            files = response.get("files", [])

            for file in files:
                google_file_id = file.get("id")
                if not google_file_id:
                    continue
                scanned_google_file_ids.add(google_file_id)
                file_name = file.get("name", "")
                drive_path = f"{folder_path_prefix}/{file_name}" if folder_path_prefix else file_name
                items.append(_file_to_upsert_item(file, drive_path))

            page_token = response.get("nextPageToken")
            if not page_token:
                break

    upsert_count, metadata_updates = _batch_upsert(api_client, conn, items)
    if metadata_updates:
        api_client.update_metadata(
            conn.connection_id,
            lease_token=conn.lease_token,
            updates=metadata_updates,
        )

    reconcile_count = _reconcile_deleted_files(api_client, conn, scanned_google_file_ids)
    return upsert_count + reconcile_count


def _incremental_sync_folder(
    api_client: InternalAPIClient, service: Any, conn: Any,
    detected_drive_id: str | None = None,
) -> int:
    monitored_ids: set[str] = {conn.folder_id}
    try:
        subfolder_ids = _list_subfolders(service, conn.folder_id)
        monitored_ids.update(subfolder_ids)
    except Exception:
        logger.warning("incremental_subfolder_listing_failed", exc_info=True)

    folder_path_prefix = conn.folder_path or conn.folder_name or ""
    page_token = conn.change_token
    items_to_upsert: list[dict[str, Any]] = []
    file_ids_to_delete: list[str] = []

    while True:
        kwargs: dict[str, Any] = {
            "pageToken": page_token,
            "fields": "nextPageToken,newStartPageToken,changes(fileId,removed,file(id,name,mimeType,size,md5Checksum,modifiedTime,trashed,parents,webViewLink))",
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
        }
        if conn.drive_id:
            kwargs["driveId"] = conn.drive_id
        else:
            kwargs["restrictToMyDrive"] = True

        response = service.changes().list(**kwargs).execute()

        for change in response.get("changes", []):
            file_id = change.get("fileId")
            is_removed = change.get("removed", False)
            file_data = change.get("file", {})
            is_trashed = file_data.get("trashed", False)
            parents = file_data.get("parents", [])

            if (
                file_data.get("mimeType") == "application/vnd.google-apps.folder"
                and not is_removed
                and not is_trashed
                and parents
                and parents[0] in monitored_ids
            ):
                new_folder_id = file_data.get("id")
                if new_folder_id:
                    monitored_ids.add(new_folder_id)

            if not is_removed and (not parents or parents[0] not in monitored_ids):
                continue

            if is_removed or is_trashed:
                if file_id:
                    file_ids_to_delete.append(file_id)
                continue

            mime_type = file_data.get("mimeType", "")
            if not is_supported_mime(mime_type):
                continue

            file_name = file_data.get("name", "")
            drive_path = f"{folder_path_prefix}/{file_name}" if folder_path_prefix else file_name
            items_to_upsert.append(_file_to_upsert_item(file_data, drive_path))

        if "newStartPageToken" in response:
            new_token = response["newStartPageToken"]
            break
        page_token = response["nextPageToken"]

    upsert_count = 0
    if items_to_upsert:
        upsert_count, metadata_updates = _batch_upsert(api_client, conn, items_to_upsert)
        if metadata_updates:
            api_client.update_metadata(
                conn.connection_id,
                lease_token=conn.lease_token,
                updates=metadata_updates,
            )

    delete_count = 0
    if file_ids_to_delete:
        delete_count = _batch_delete(api_client, conn, file_ids_to_delete)

    api_client.checkpoint(
        conn.connection_id,
        lease_token=conn.lease_token,
        change_token=new_token,
        drive_id=detected_drive_id,
        release=False,
    )

    logger.info(
        "incremental_sync_folder_complete",
        extra={
            "org_id": str(conn.org_id),
            "connection_id": str(conn.connection_id),
            "folder_id": conn.folder_id,
            "upserted": upsert_count,
            "deleted": delete_count,
            "monitored_folders": len(monitored_ids),
        },
    )

    return upsert_count + delete_count


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
    created_time = file.get("createdTime")
    if created_time:
        item["created_time"] = created_time
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
) -> tuple[int, list[dict[str, str]]]:
    if not items:
        return 0, []

    total_created = 0
    all_metadata_updates: list[dict[str, str]] = []
    for i in range(0, len(items), _MAX_UPSERT_BATCH):
        batch = items[i : i + _MAX_UPSERT_BATCH]
        result = api_client.upsert_files(
            conn.connection_id,
            lease_token=conn.lease_token,
            items=batch,
        )
        total_created += result.created_count
        all_metadata_updates.extend(result.metadata_updates)

    return total_created, all_metadata_updates


def _reconcile_deleted_files(
    api_client: InternalAPIClient,
    conn: Any,
    scanned_google_file_ids: set[str],
) -> int:
    existing_file_ids = api_client.list_connection_file_ids(conn.connection_id)
    deleted_ids = existing_file_ids - scanned_google_file_ids

    if not deleted_ids:
        logger.info(
            "reconcile_no_deletions",
            extra={
                "connection_id": str(conn.connection_id),
                "scanned": len(scanned_google_file_ids),
            },
        )
        return 0

    logger.info(
        "reconcile_detected_deletions",
        extra={
            "connection_id": str(conn.connection_id),
            "scanned": len(scanned_google_file_ids),
            "existing": len(existing_file_ids),
            "to_delete": len(deleted_ids),
        },
    )
    return _batch_delete(api_client, conn, list(deleted_ids))


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
                "supportsAllDrives": True,
                "includeItemsFromAllDrives": True,
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
