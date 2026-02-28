from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
from unittest.mock import MagicMock
from uuid import uuid4


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
    conn.change_token = change_token
    conn.last_full_sync_at = last_full_sync_at
    return conn


def test_incremental_sync_uses_change_token(monkeypatch):
    api_client = MagicMock()
    service = MagicMock()
    conn = _make_conn(
        change_token="token-1",
        last_full_sync_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
    )

    monkeypatch.setattr(discover, "_batch_upsert", lambda *_: 0)
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

    files_resource = service.files.return_value
    files_resource.list.return_value.execute.return_value = {"files": []}
    service.changes.return_value.getStartPageToken.return_value.execute.return_value = {
        "startPageToken": "fresh-token"
    }

    result = discover._discover_drive_connection(api_client, service, conn, settings=MagicMock())

    assert result == 0
    assert files_resource.list.call_count == 1
    assert service.changes.return_value.list.call_count == 0
