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

    return mod._should_ingest_file, mod._is_image_mime


_should_ingest_file, _is_image_mime = _import_filtering_functions()


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
