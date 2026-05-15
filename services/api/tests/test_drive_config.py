import os

import pytest
from unittest.mock import patch

from app.config import Settings

# Env vars that staging Docker sets which override code defaults.
# We clear them so tests see the real code defaults.
_DRIVE_ENV_KEYS = [
    "DRIVE_CONNECTOR_ENABLED",
    "DRIVE_S3_BUCKET",
    "DRIVE_ENRICHMENT_ENABLED",
    "DRIVE_WORKER_GLOBAL_CONCURRENCY",
    "DRIVE_WORKER_PER_ORG_CONCURRENCY",
    "DRIVE_TEMP_DISK_BUDGET_GB",
    "DRIVE_PROXY_MAX_HEIGHT",
    "DRIVE_PROXY_CRF",
    "DRIVE_PROXY_PRESET",
    "DRIVE_PROXY_AUDIO_BITRATE",
    "DRIVE_PROXY_MAX_BITRATE",
    "DRIVE_PROXY_BUFSIZE",
    "DRIVE_DOWNLOAD_CHUNK_SIZE",
    "DRIVE_DOWNLOAD_MAX_RETRIES",
]


def _isolated_settings(**kwargs):
    """Create Settings without reading .env file and with drive env vars cleared."""
    clean_env = {k: v for k, v in os.environ.items() if k not in _DRIVE_ENV_KEYS}
    with patch.dict("os.environ", clean_env, clear=True):
        return Settings(_env_file="", **kwargs)


class TestDriveConfig:
    def test_drive_connector_disabled_by_default(self):
        settings = _isolated_settings()
        assert settings.drive_connector_enabled is False

    def test_drive_default_concurrency(self):
        settings = _isolated_settings()
        assert settings.drive_worker_global_concurrency == 2
        assert settings.drive_worker_per_org_concurrency == 1

    def test_drive_default_disk_budget(self):
        settings = _isolated_settings()
        assert settings.drive_temp_disk_budget_gb == 50.0

    def test_drive_default_proxy_settings(self):
        settings = _isolated_settings()
        assert settings.drive_proxy_max_height == 720
        assert settings.drive_proxy_crf == 23
        assert settings.drive_proxy_preset == "fast"
        assert settings.drive_proxy_audio_bitrate == "128k"
        assert settings.drive_proxy_max_bitrate == "2500k"
        assert settings.drive_proxy_bufsize == "5000k"

    def test_drive_default_download_settings(self):
        settings = _isolated_settings()
        assert settings.drive_download_chunk_size == 10 * 1024 * 1024
        assert settings.drive_download_max_retries == 3

    def test_drive_default_s3_bucket(self):
        settings = _isolated_settings()
        assert settings.drive_s3_bucket == "heimdex-drive"

    def test_drive_enrichment_disabled_by_default(self):
        settings = _isolated_settings()
        assert settings.drive_enrichment_enabled is False

    def test_drive_settings_from_env(self):
        with patch.dict("os.environ", {
            "DRIVE_CONNECTOR_ENABLED": "true",
            "DRIVE_WORKER_GLOBAL_CONCURRENCY": "4",
            "DRIVE_WORKER_PER_ORG_CONCURRENCY": "2",
            "DRIVE_TEMP_DISK_BUDGET_GB": "100",
        }):
            settings = Settings(_env_file="")
            assert settings.drive_connector_enabled is True
            assert settings.drive_worker_global_concurrency == 4
            assert settings.drive_worker_per_org_concurrency == 2
            assert settings.drive_temp_disk_budget_gb == 100.0
