import pytest
from unittest.mock import patch

from app.config import Settings


class TestDriveConfig:
    def test_drive_connector_disabled_by_default(self):
        settings = Settings()
        assert settings.drive_connector_enabled is False

    def test_drive_default_concurrency(self):
        settings = Settings()
        assert settings.drive_worker_global_concurrency == 2
        assert settings.drive_worker_per_org_concurrency == 1

    def test_drive_default_disk_budget(self):
        settings = Settings()
        assert settings.drive_temp_disk_budget_gb == 50.0

    def test_drive_default_proxy_settings(self):
        settings = Settings()
        assert settings.drive_proxy_max_height == 720
        assert settings.drive_proxy_crf == 23
        assert settings.drive_proxy_preset == "fast"
        assert settings.drive_proxy_audio_bitrate == "128k"
        assert settings.drive_proxy_max_bitrate == "2500k"
        assert settings.drive_proxy_bufsize == "5000k"

    def test_drive_default_download_settings(self):
        settings = Settings()
        assert settings.drive_download_chunk_size == 10 * 1024 * 1024
        assert settings.drive_download_max_retries == 3

    def test_drive_default_s3_bucket(self):
        settings = Settings()
        assert settings.drive_s3_bucket == "heimdex-drive"

    def test_drive_settings_from_env(self):
        with patch.dict("os.environ", {
            "DRIVE_CONNECTOR_ENABLED": "true",
            "DRIVE_WORKER_GLOBAL_CONCURRENCY": "4",
            "DRIVE_WORKER_PER_ORG_CONCURRENCY": "2",
            "DRIVE_TEMP_DISK_BUDGET_GB": "100",
        }):
            settings = Settings()
            assert settings.drive_connector_enabled is True
            assert settings.drive_worker_global_concurrency == 4
            assert settings.drive_worker_per_org_concurrency == 2
            assert settings.drive_temp_disk_budget_gb == 100.0
