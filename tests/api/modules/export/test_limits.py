"""Tests for export size estimation and proxy deduplication."""

from __future__ import annotations

import sys
import types
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# limits.py imports DriveFile from app.modules.drive.models.
# We stub that module so spec_from_file_location can load limits.py standalone.
_drive_models_stub = types.ModuleType("app.modules.drive.models")
_drive_models_stub.DriveFile = type("DriveFile", (), {})  # type: ignore[attr-defined]

# Build the app.modules.drive namespace chain
for name in ["app", "app.modules", "app.modules.drive", "app.modules.drive.models"]:
    if name not in sys.modules:
        sys.modules[name] = (
            _drive_models_stub if name == "app.modules.drive.models"
            else types.ModuleType(name)
        )

MODULE_PATH = (
    Path(__file__).resolve().parents[4]
    / "services"
    / "api"
    / "app"
    / "modules"
    / "export"
    / "limits.py"
)
SPEC = spec_from_file_location("limits", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
_mod = module_from_spec(SPEC)
SPEC.loader.exec_module(_mod)

ExportSizeEstimate = _mod.ExportSizeEstimate
estimate_export_size = _mod.estimate_export_size
deduplicate_proxies = _mod.deduplicate_proxies


def _make_drive_file(
    proxy_s3_key: str | None = "org/drive/xxx/proxy.mp4",
    proxy_size_bytes: int | None = 10_000_000,
) -> MagicMock:
    """Create a mock DriveFile with proxy info."""
    df = MagicMock()
    df.proxy_s3_key = proxy_s3_key
    df.proxy_size_bytes = proxy_size_bytes
    return df


class TestEstimateExportSize:
    def test_basic_estimation(self):
        files = {
            "gd_v1": _make_drive_file(proxy_size_bytes=10_000_000),
            "gd_v2": _make_drive_file(proxy_size_bytes=20_000_000),
        }
        est = estimate_export_size(deduplicated_files=files, clip_count=3)

        assert est.proxy_bytes == 30_000_000
        assert est.metadata_bytes == 50_000
        assert est.zip_overhead_bytes == 30_000  # 0.1% of proxy_bytes
        assert est.total_bytes == 30_000_000 + 50_000 + 30_000
        assert est.proxy_count == 2
        assert est.clip_count == 3

    def test_empty_files(self):
        est = estimate_export_size(deduplicated_files={}, clip_count=0)
        assert est.proxy_bytes == 0
        assert est.total_bytes == 50_000  # just metadata
        assert est.proxy_count == 0
        assert est.clip_count == 0

    def test_file_without_proxy_key_excluded(self):
        files = {
            "gd_v1": _make_drive_file(proxy_s3_key=None, proxy_size_bytes=10_000_000),
        }
        est = estimate_export_size(deduplicated_files=files, clip_count=1)
        assert est.proxy_bytes == 0
        assert est.proxy_count == 1  # still counted as a file entry

    def test_file_with_none_size_treated_as_zero(self):
        files = {
            "gd_v1": _make_drive_file(proxy_size_bytes=None),
        }
        est = estimate_export_size(deduplicated_files=files, clip_count=1)
        assert est.proxy_bytes == 0

    def test_returns_frozen_dataclass(self):
        est = estimate_export_size(deduplicated_files={}, clip_count=0)
        assert isinstance(est, ExportSizeEstimate)
        with pytest.raises(AttributeError):
            est.total_bytes = 999  # type: ignore[misc]


class TestDeduplicateProxies:
    def test_dedup_multiple_clips_same_video(self):
        clips = [
            {"scene_id": "s1", "video_id": "gd_v1", "start_ms": 0, "end_ms": 5000},
            {"scene_id": "s2", "video_id": "gd_v1", "start_ms": 5000, "end_ms": 10000},
        ]
        df1 = _make_drive_file()
        drive_files = {"gd_v1": df1}

        result = deduplicate_proxies(clips, drive_files)
        assert len(result) == 1
        assert "gd_v1" in result

    def test_dedup_different_videos(self):
        clips = [
            {"scene_id": "s1", "video_id": "gd_v1", "start_ms": 0, "end_ms": 5000},
            {"scene_id": "s2", "video_id": "gd_v2", "start_ms": 0, "end_ms": 5000},
        ]
        drive_files = {
            "gd_v1": _make_drive_file(),
            "gd_v2": _make_drive_file(),
        }

        result = deduplicate_proxies(clips, drive_files)
        assert len(result) == 2

    def test_clip_referencing_missing_drive_file_skipped(self):
        clips = [
            {"scene_id": "s1", "video_id": "gd_v1", "start_ms": 0, "end_ms": 5000},
            {"scene_id": "s2", "video_id": "gd_missing", "start_ms": 0, "end_ms": 5000},
        ]
        drive_files = {"gd_v1": _make_drive_file()}

        result = deduplicate_proxies(clips, drive_files)
        assert len(result) == 1
        assert "gd_v1" in result
        assert "gd_missing" not in result

    def test_empty_clips(self):
        result = deduplicate_proxies([], {})
        assert result == {}