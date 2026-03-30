"""Unit tests for watched folder filtering logic in discover.py.

These tests exercise _should_ingest_file and _is_image_mime independently
of the Google API client (no google.oauth2 import required).
"""
import importlib
import sys
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock


def _import_filtering_functions():
    """Import discover module with Google API mocked out."""
    fake_google = ModuleType("google")
    fake_oauth2 = ModuleType("google.oauth2")
    fake_creds = ModuleType("google.oauth2.credentials")
    fake_creds.Credentials = MagicMock  # type: ignore[attr-defined]
    fake_google.oauth2 = fake_oauth2  # type: ignore[attr-defined]
    fake_oauth2.credentials = fake_creds  # type: ignore[attr-defined]

    fake_discovery = ModuleType("googleapiclient")
    fake_disc_mod = ModuleType("googleapiclient.discovery")
    fake_disc_mod.build = MagicMock  # type: ignore[attr-defined]
    fake_errors = ModuleType("googleapiclient.errors")
    fake_errors.HttpError = type("HttpError", (Exception,), {})  # type: ignore[attr-defined]
    fake_discovery.discovery = fake_disc_mod  # type: ignore[attr-defined]
    fake_discovery.errors = fake_errors  # type: ignore[attr-defined]

    stash = {}
    for mod_name in [
        "google", "google.oauth2", "google.oauth2.credentials",
        "googleapiclient", "googleapiclient.discovery", "googleapiclient.errors",
    ]:
        stash[mod_name] = sys.modules.get(mod_name)
        sys.modules[mod_name] = {
            "google": fake_google,
            "google.oauth2": fake_oauth2,
            "google.oauth2.credentials": fake_creds,
            "googleapiclient": fake_discovery,
            "googleapiclient.discovery": fake_disc_mod,
            "googleapiclient.errors": fake_errors,
        }[mod_name]

    try:
        if "src.tasks.discover" in sys.modules:
            mod = importlib.reload(sys.modules["src.tasks.discover"])
        else:
            mod = importlib.import_module("src.tasks.discover")
    finally:
        for mod_name, original in stash.items():
            if original is None:
                sys.modules.pop(mod_name, None)
            else:
                sys.modules[mod_name] = original

    return mod._should_ingest_file, mod._is_image_mime, mod._expand_watched_folder_ids


_should_ingest_file, _is_image_mime, _expand_watched_folder_ids = _import_filtering_functions()


def test_file_in_watched_folder_video_allowed():
    file_data: dict[str, Any] = {"mimeType": "video/mp4", "parents": ["folder-1"]}
    assert _should_ingest_file(file_data, {"folder-1"}, {"folder-1": ["video"]}) is True


def test_file_in_watched_folder_image_allowed():
    file_data: dict[str, Any] = {"mimeType": "image/jpeg", "parents": ["folder-1"]}
    assert _should_ingest_file(file_data, {"folder-1"}, {"folder-1": ["image"]}) is True


def test_file_in_watched_folder_both_allowed():
    file_data: dict[str, Any] = {"mimeType": "video/mp4", "parents": ["folder-1"]}
    assert _should_ingest_file(file_data, {"folder-1"}, {"folder-1": ["video", "image"]}) is True


def test_file_not_in_watched_folder():
    file_data: dict[str, Any] = {"mimeType": "video/mp4", "parents": ["folder-2"]}
    assert _should_ingest_file(file_data, {"folder-1"}, {"folder-1": ["video"]}) is False


def test_file_no_parents():
    file_data: dict[str, Any] = {"mimeType": "video/mp4"}
    assert _should_ingest_file(file_data, {"folder-1"}, {"folder-1": ["video"]}) is False


def test_file_wrong_content_type():
    file_data: dict[str, Any] = {"mimeType": "image/jpeg", "parents": ["folder-1"]}
    assert _should_ingest_file(file_data, {"folder-1"}, {"folder-1": ["video"]}) is False


def test_video_in_image_only_folder():
    file_data: dict[str, Any] = {"mimeType": "video/mp4", "parents": ["folder-1"]}
    assert _should_ingest_file(file_data, {"folder-1"}, {"folder-1": ["image"]}) is False


def test_supported_image_mimes():
    assert _is_image_mime("image/jpeg") is True
    assert _is_image_mime("image/png") is True
    assert _is_image_mime("image/webp") is True
    assert _is_image_mime("image/gif") is True
    assert _is_image_mime("image/bmp") is True
    assert _is_image_mime("image/tiff") is True


def test_unsupported_mimes():
    assert _is_image_mime("video/mp4") is False
    assert _is_image_mime("application/pdf") is False
    assert _is_image_mime("text/plain") is False


# ── Subfolder expansion tests ────────────────────────────────────────────────


def test_file_in_subfolder_of_watched_folder():
    """Files in subfolders of watched folders should be ingested."""
    file_data: dict[str, Any] = {"mimeType": "video/mp4", "parents": ["subfolder-1"]}
    watched_ids = {"folder-1", "subfolder-1"}
    types_map = {"folder-1": ["video"], "subfolder-1": ["video"]}
    assert _should_ingest_file(file_data, watched_ids, types_map) is True


def test_subfolder_inherits_content_types():
    """Subfolders inherit ancestor's content_types."""
    file_data: dict[str, Any] = {"mimeType": "image/jpeg", "parents": ["subfolder-1"]}
    watched_ids = {"folder-1", "subfolder-1"}
    types_map = {"folder-1": ["image"], "subfolder-1": ["image"]}
    assert _should_ingest_file(file_data, watched_ids, types_map) is True


def test_subfolder_rejects_wrong_content_type():
    """Subfolders respect inherited content_types filter."""
    file_data: dict[str, Any] = {"mimeType": "image/jpeg", "parents": ["subfolder-1"]}
    watched_ids = {"folder-1", "subfolder-1"}
    types_map = {"folder-1": ["video"], "subfolder-1": ["video"]}
    assert _should_ingest_file(file_data, watched_ids, types_map) is False


def test_expand_watched_folder_ids_no_subfolders():
    """Expansion with no subfolders returns only top-level IDs."""
    mock_service = MagicMock()
    mock_service.files.return_value.list.return_value.execute.return_value = {"files": []}
    watched = [{"google_folder_id": "folder-1", "content_types": ["video"]}]
    ids, types_map = _expand_watched_folder_ids(mock_service, watched)
    assert ids == {"folder-1"}
    assert types_map == {"folder-1": ["video"]}


def test_expand_watched_folder_ids_with_subfolders():
    """Expansion includes subfolder IDs with inherited content_types."""
    mock_service = MagicMock()
    # First call: folder-1 has one subfolder sub-1
    # Second call: sub-1 has no subfolders (stops recursion)
    mock_service.files.return_value.list.return_value.execute.side_effect = [
        {"files": [{"id": "sub-1"}]},
        {"files": []},
    ]
    watched = [{"google_folder_id": "folder-1", "content_types": ["video", "image"]}]
    ids, types_map = _expand_watched_folder_ids(mock_service, watched)
    assert "folder-1" in ids
    assert "sub-1" in ids
    assert types_map["sub-1"] == ["video", "image"]


def test_expand_watched_folder_ids_failure_partial():
    """If one folder fails expansion, others still succeed."""
    mock_service = MagicMock()

    # First call: folder-bad fails
    # Second call: folder-ok has one subfolder sub-2
    # Third call: sub-2 has no subfolders (stops recursion)
    mock_service.files.return_value.list.return_value.execute.side_effect = [
        Exception("API error"),
        {"files": [{"id": "sub-2"}]},
        {"files": []},
    ]
    watched = [
        {"google_folder_id": "folder-bad", "content_types": ["video"]},
        {"google_folder_id": "folder-ok", "content_types": ["image"]},
    ]
    ids, types_map = _expand_watched_folder_ids(mock_service, watched)
    assert "folder-bad" in ids  # top-level still included
    assert "folder-ok" in ids
    assert "sub-2" in ids
    assert types_map["sub-2"] == ["image"]
