# pyright: reportAny=false, reportMissingParameterType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false, reportUnknownMemberType=false, reportUnknownParameterType=false, reportUnknownVariableType=false

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "worker_sdk" / "src"))

discover_path = ROOT / "services" / "drive-worker" / "src" / "tasks" / "discover.py"
spec = importlib.util.spec_from_file_location("drive_worker_discover", discover_path)
assert spec and spec.loader
discover = importlib.util.module_from_spec(spec)
spec.loader.exec_module(discover)


def _make_conn() -> SimpleNamespace:
    return SimpleNamespace(
        org_id=uuid4(),
        connection_id=uuid4(),
        lease_token="lease-token-1",
        drive_id="shared-drive-1",
    )


def test_is_supported_mime_includes_images():
    assert discover.is_supported_mime("image/jpeg") is True
    assert discover.is_supported_mime("image/png") is True
    assert discover.is_supported_mime("image/webp") is True


def test_is_supported_mime_rejects_unsupported():
    assert discover.is_supported_mime("application/pdf") is False


def test_max_image_batch_constant():
    assert discover.MAX_IMAGE_BATCH == 200


def test_full_scan_drive_query_includes_images(monkeypatch):
    api_client = MagicMock()
    service = MagicMock()
    conn = _make_conn()

    service.files.return_value.list.return_value.execute.return_value = {"files": []}

    monkeypatch.setattr(discover, "_batch_upsert", lambda *_args, **_kwargs: (0, []))
    monkeypatch.setattr(discover, "_reconcile_deleted_files", lambda *_args, **_kwargs: 0)

    discover._full_scan_drive(api_client, service, conn)

    q = service.files.return_value.list.call_args.kwargs["q"]
    assert "mimeType='image/jpeg'" in q
    assert "mimeType='image/png'" in q
    assert "mimeType='image/webp'" in q


def test_image_throttle_limits_images(monkeypatch):
    api_client = MagicMock()
    service = MagicMock()
    conn = _make_conn()

    files = [
        {
            "id": f"img_{i}",
            "name": f"img_{i}.jpg",
            "mimeType": "image/jpeg",
            "size": "10",
        }
        for i in range(250)
    ]
    service.files.return_value.list.return_value.execute.return_value = {"files": files}

    captured = {"upsert_items": 0}

    def _fake_batch_upsert(_api_client, _conn, items):
        captured["upsert_items"] = len(items)
        return len(items), []

    monkeypatch.setattr(discover, "_batch_upsert", _fake_batch_upsert)
    monkeypatch.setattr(discover, "_resolve_folder_paths", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(discover, "_reconcile_deleted_files", lambda *_args, **_kwargs: 0)

    discover._full_scan_drive(api_client, service, conn)

    assert captured["upsert_items"] == 200


def test_image_throttle_does_not_limit_videos(monkeypatch):
    api_client = MagicMock()
    service = MagicMock()
    conn = _make_conn()

    files = [
        {
            "id": f"vid_{i}",
            "name": f"vid_{i}.mp4",
            "mimeType": "video/mp4",
            "size": "10",
        }
        for i in range(300)
    ]
    service.files.return_value.list.return_value.execute.return_value = {"files": files}

    captured = {"upsert_items": 0}

    def _fake_batch_upsert(_api_client, _conn, items):
        captured["upsert_items"] = len(items)
        return len(items), []

    monkeypatch.setattr(discover, "_batch_upsert", _fake_batch_upsert)
    monkeypatch.setattr(discover, "_resolve_folder_paths", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(discover, "_reconcile_deleted_files", lambda *_args, **_kwargs: 0)

    discover._full_scan_drive(api_client, service, conn)

    assert captured["upsert_items"] == 300
