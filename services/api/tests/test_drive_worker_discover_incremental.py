from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
from unittest.mock import MagicMock
from uuid import uuid4

from googleapiclient.errors import HttpError


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "worker_sdk" / "src"))
discover_path = ROOT / "services" / "drive-worker" / "src" / "tasks" / "discover.py"
spec = importlib.util.spec_from_file_location("drive_worker_discover", discover_path)
assert spec and spec.loader
discover = importlib.util.module_from_spec(spec)
spec.loader.exec_module(discover)


def _make_conn(*, change_token: str | None, last_full_sync_at: str | None) -> MagicMock:
    conn = MagicMock()
    conn.org_id = uuid4()
    conn.connection_id = uuid4()
    conn.lease_token = str(uuid4())
    conn.drive_id = "shared-drive-1"
    conn.folder_id = None
    conn.folder_name = None
    conn.folder_path = None
    conn.change_token = change_token
    conn.last_full_sync_at = last_full_sync_at
    return conn


def _make_folder_conn(*, change_token: str | None, last_full_sync_at: str | None, drive_id: str | None) -> MagicMock:
    conn = _make_conn(change_token=change_token, last_full_sync_at=last_full_sync_at)
    conn.drive_id = drive_id
    conn.folder_id = "folder-root"
    conn.folder_name = "Folder Root"
    conn.folder_path = "Folder Root"
    return conn


def test_incremental_sync_uses_change_token(monkeypatch):
    api_client = MagicMock()
    service = MagicMock()
    conn = _make_conn(
        change_token="token-1",
        last_full_sync_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
    )

    monkeypatch.setattr(discover, "_batch_upsert", lambda *_: (0, []))
    monkeypatch.setattr(discover, "_batch_delete", lambda *_: 0)

    changes_resource = service.changes.return_value
    changes_resource.list.return_value.execute.return_value = {
        "changes": [],
        "newStartPageToken": "token-2",
    }

    result = discover._discover_drive_connection(api_client, service, conn, settings=MagicMock())

    assert result == 0
    assert changes_resource.list.call_count == 1
    assert service.files.return_value.list.call_count == 0


def test_full_scan_when_no_token():
    api_client = MagicMock()
    service = MagicMock()
    conn = _make_conn(change_token=None, last_full_sync_at=None)
    api_client.list_connection_file_ids.return_value = set()

    files_resource = service.files.return_value
    files_resource.list.return_value.execute.return_value = {"files": []}
    service.changes.return_value.getStartPageToken.return_value.execute.return_value = {
        "startPageToken": "start-token"
    }

    result = discover._discover_drive_connection(api_client, service, conn, settings=MagicMock())

    assert result == 0
    assert files_resource.list.call_count == 1


def test_full_scan_when_token_stale():
    api_client = MagicMock()
    service = MagicMock()
    conn = _make_conn(
        change_token="old-token",
        last_full_sync_at=(datetime.now(timezone.utc) - timedelta(days=8)).isoformat(),
    )
    api_client.list_connection_file_ids.return_value = set()

    files_resource = service.files.return_value
    files_resource.list.return_value.execute.return_value = {"files": []}
    service.changes.return_value.getStartPageToken.return_value.execute.return_value = {
        "startPageToken": "fresh-token"
    }

    result = discover._discover_drive_connection(api_client, service, conn, settings=MagicMock())

    assert result == 0
    assert files_resource.list.call_count == 1
    assert service.changes.return_value.list.call_count == 0


def test_reconcile_detects_deletions(monkeypatch):
    api_client = MagicMock()
    conn = _make_conn(change_token=None, last_full_sync_at=None)
    api_client.list_connection_file_ids.return_value = {"keep", "delete_1", "delete_2"}

    captured: dict[str, list[str]] = {}

    def _fake_batch_delete(_api_client, _conn, file_ids):
        captured["ids"] = list(file_ids)
        return len(file_ids)

    monkeypatch.setattr(discover, "_batch_delete", _fake_batch_delete)

    deleted_count = discover._reconcile_deleted_files(
        api_client,
        conn,
        {"keep"},
    )

    assert deleted_count == 2
    assert set(captured["ids"]) == {"delete_1", "delete_2"}


def test_reconcile_no_deletions(monkeypatch):
    api_client = MagicMock()
    conn = _make_conn(change_token=None, last_full_sync_at=None)
    api_client.list_connection_file_ids.return_value = {"a", "b"}

    monkeypatch.setattr(discover, "_batch_delete", lambda *_: 99)

    deleted_count = discover._reconcile_deleted_files(
        api_client,
        conn,
        {"a", "b"},
    )

    assert deleted_count == 0


def test_full_scan_with_reconciliation(monkeypatch):
    api_client = MagicMock()
    service = MagicMock()
    conn = _make_conn(change_token=None, last_full_sync_at=None)

    service.files.return_value.list.return_value.execute.return_value = {
        "files": [
            {
                "id": "file_a",
                "name": "video_a.mp4",
                "mimeType": "video/mp4",
                "size": "100",
                "md5Checksum": "md5-a",
                "modifiedTime": "2026-02-26T00:00:00Z",
            },
            {
                "id": "file_b",
                "name": "video_b.mp4",
                "mimeType": "video/mp4",
                "size": "200",
                "md5Checksum": "md5-b",
                "modifiedTime": "2026-02-26T00:00:00Z",
            },
        ]
    }

    monkeypatch.setattr(discover, "_resolve_folder_paths", lambda *_: {})

    def _fake_batch_upsert(_api_client, _conn, items):
        assert len(items) == 2
        return 2, [{"video_id": "vid_1", "video_title": "renamed.mp4"}]

    monkeypatch.setattr(discover, "_batch_upsert", _fake_batch_upsert)

    captured_updates: dict[str, object] = {}

    def _fake_update_metadata(connection_id, *, lease_token, updates):
        captured_updates["connection_id"] = connection_id
        captured_updates["lease_token"] = lease_token
        captured_updates["updates"] = updates
        return MagicMock(updated_scene_count=3, skipped_count=0)

    api_client.update_metadata.side_effect = _fake_update_metadata
    api_client.list_connection_file_ids.return_value = {"file_a", "file_b", "file_c"}
    monkeypatch.setattr(discover, "_batch_delete", lambda *_: 1)

    result = discover._full_scan_drive(api_client, service, conn)

    assert result == 3
    assert captured_updates["connection_id"] == conn.connection_id
    assert captured_updates["lease_token"] == conn.lease_token
    assert captured_updates["updates"] == [{"video_id": "vid_1", "video_title": "renamed.mp4"}]


def test_folder_incremental_sync_routes_correctly(monkeypatch):
    api_client = MagicMock()
    service = MagicMock()
    conn = _make_folder_conn(
        change_token="token-1",
        last_full_sync_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        drive_id=None,
    )

    monkeypatch.setattr(discover, "_incremental_sync_folder", lambda *_: 7)
    monkeypatch.setattr(discover, "_full_scan_folder", lambda *_: (_ for _ in ()).throw(RuntimeError("should not full scan")))

    result = discover._discover_folder_connection(api_client, service, conn, settings=MagicMock())
    assert result == 7


def test_folder_full_scan_when_no_change_token(monkeypatch):
    api_client = MagicMock()
    service = MagicMock()
    conn = _make_folder_conn(change_token=None, last_full_sync_at=None, drive_id=None)

    monkeypatch.setattr(discover, "_full_scan_folder", lambda *_: 3)
    service.changes.return_value.getStartPageToken.return_value.execute.return_value = {
        "startPageToken": "start-token"
    }

    result = discover._discover_folder_connection(api_client, service, conn, settings=MagicMock())
    assert result == 3
    service.changes.return_value.getStartPageToken.assert_called_once_with(supportsAllDrives=True)
    assert api_client.checkpoint.call_count == 1


def test_folder_full_scan_when_stale(monkeypatch):
    api_client = MagicMock()
    service = MagicMock()
    conn = _make_folder_conn(
        change_token="stale-token",
        last_full_sync_at=(datetime.now(timezone.utc) - timedelta(days=8)).isoformat(),
        drive_id="shared-drive-1",
    )

    monkeypatch.setattr(discover, "_full_scan_folder", lambda *_: 2)
    monkeypatch.setattr(discover, "_incremental_sync_folder", lambda *_: (_ for _ in ()).throw(RuntimeError("should not incremental")))
    service.changes.return_value.getStartPageToken.return_value.execute.return_value = {
        "startPageToken": "fresh-token"
    }

    result = discover._discover_folder_connection(api_client, service, conn, settings=MagicMock())
    assert result == 2
    service.changes.return_value.getStartPageToken.assert_called_once_with(
        supportsAllDrives=True,
        driveId="shared-drive-1",
    )


def test_folder_incremental_filters_by_ancestry(monkeypatch):
    api_client = MagicMock()
    service = MagicMock()
    conn = _make_folder_conn(change_token="token-1", last_full_sync_at=None, drive_id=None)

    monkeypatch.setattr(discover, "_list_subfolders", lambda *_: ["folder-child"])

    captured_items: list[dict[str, str]] = []

    def _fake_batch_upsert(_api_client, _conn, items):
        captured_items.extend(items)
        return len(items), []

    monkeypatch.setattr(discover, "_batch_upsert", _fake_batch_upsert)
    monkeypatch.setattr(discover, "_batch_delete", lambda *_: 0)

    service.changes.return_value.list.return_value.execute.return_value = {
        "changes": [
            {
                "fileId": "outside-video",
                "removed": False,
                "file": {
                    "id": "outside-video",
                    "name": "outside.mp4",
                    "mimeType": "video/mp4",
                    "parents": ["outside-folder"],
                    "trashed": False,
                },
            },
            {
                "fileId": "inside-video",
                "removed": False,
                "file": {
                    "id": "inside-video",
                    "name": "inside.mp4",
                    "mimeType": "video/mp4",
                    "parents": ["folder-child"],
                    "trashed": False,
                },
            },
        ],
        "newStartPageToken": "token-2",
    }

    result = discover._incremental_sync_folder(api_client, service, conn)

    assert result == 1
    assert len(captured_items) == 1
    assert captured_items[0]["provider_file_id"] == "inside-video"
    assert captured_items[0]["drive_path"] == "Folder Root/inside.mp4"
    assert service.changes.return_value.list.call_args.kwargs["restrictToMyDrive"] is True


def test_folder_incremental_detects_new_subfolder(monkeypatch):
    api_client = MagicMock()
    service = MagicMock()
    conn = _make_folder_conn(change_token="token-1", last_full_sync_at=None, drive_id="shared-drive-1")

    monkeypatch.setattr(discover, "_list_subfolders", lambda *_: [])
    captured_items: list[dict[str, str]] = []
    monkeypatch.setattr(
        discover,
        "_batch_upsert",
        lambda _api_client, _conn, items: (captured_items.extend(items) or len(items), []),
    )
    monkeypatch.setattr(discover, "_batch_delete", lambda *_: 0)

    service.changes.return_value.list.return_value.execute.return_value = {
        "changes": [
            {
                "fileId": "folder-new",
                "removed": False,
                "file": {
                    "id": "folder-new",
                    "name": "Subfolder",
                    "mimeType": "application/vnd.google-apps.folder",
                    "parents": ["folder-root"],
                    "trashed": False,
                },
            },
            {
                "fileId": "video-new",
                "removed": False,
                "file": {
                    "id": "video-new",
                    "name": "new.mp4",
                    "mimeType": "video/mp4",
                    "parents": ["folder-new"],
                    "trashed": False,
                },
            },
        ],
        "newStartPageToken": "token-2",
    }

    result = discover._incremental_sync_folder(api_client, service, conn)

    assert result == 1
    assert len(captured_items) == 1
    assert captured_items[0]["provider_file_id"] == "video-new"
    assert service.changes.return_value.list.call_args.kwargs["driveId"] == "shared-drive-1"


def test_folder_410_recovery(monkeypatch):
    api_client = MagicMock()
    service = MagicMock()
    conn = _make_folder_conn(
        change_token="token-1",
        last_full_sync_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        drive_id=None,
    )

    expired_error = HttpError(resp=MagicMock(status=410, reason="Gone"), content=b"expired", uri="https://drive")
    monkeypatch.setattr(discover, "_incremental_sync_folder", lambda *_: (_ for _ in ()).throw(expired_error))
    monkeypatch.setattr(discover, "_full_scan_folder", lambda *_: 5)
    service.changes.return_value.getStartPageToken.return_value.execute.return_value = {
        "startPageToken": "fresh-token"
    }

    result = discover._discover_folder_connection(api_client, service, conn, settings=MagicMock())
    assert result == 5
