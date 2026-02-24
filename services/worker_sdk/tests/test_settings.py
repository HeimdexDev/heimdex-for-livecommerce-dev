"""Tests for heimdex_worker_sdk.settings — WorkerSettings field parity and loading."""

import os
from unittest.mock import patch

import pytest

from heimdex_worker_sdk.settings import WorkerSettings, get_worker_settings


class TestWorkerSettingsDefaults:
    """Verify default values match app.config.Settings defaults exactly."""

    def test_default_environment(self):
        s = WorkerSettings()
        assert s.environment == "development"

    def test_default_log_level(self):
        s = WorkerSettings()
        assert s.log_level == "INFO"

    def test_default_minio_settings(self):
        s = WorkerSettings()
        assert s.minio_endpoint == "localhost:9000"
        assert s.minio_access_key == "heimdex"
        assert s.minio_secret_key == "heimdex_dev_password"
        assert s.minio_secure is False

    def test_default_drive_settings(self):
        s = WorkerSettings()
        assert s.drive_s3_bucket == "heimdex-drive"
        assert s.drive_connector_enabled is False
        assert s.drive_enrichment_enabled is False
        assert s.drive_worker_poll_interval_seconds == 30
        assert s.drive_worker_global_concurrency == 2
        assert s.drive_worker_per_org_concurrency == 1

    def test_default_caption_settings(self):
        s = WorkerSettings()
        assert s.scene_caption_enabled is False
        assert s.drive_caption_concurrency == 1
        assert s.caption_engine == "internvl2"
        assert s.drive_caption_model == "OpenGVLab/InternVL2-1B"

    def test_default_stt_settings(self):
        s = WorkerSettings()
        assert s.drive_stt_enabled is False
        assert s.drive_stt_model == "small"
        assert s.drive_stt_language == "ko"
        assert s.drive_stt_backend == "faster-whisper"
        assert s.drive_stt_max_audio_seconds == 3600

    def test_default_ocr_settings(self):
        s = WorkerSettings()
        assert s.drive_ocr_enabled is False
        assert s.drive_ocr_concurrency == 1
        assert s.drive_ocr_max_frames_per_scene == 10
        assert s.drive_ocr_max_frames_per_video == 300


class TestWorkerSettingsEnvOverride:
    """Verify env vars override defaults — same env var names as API Settings."""

    def test_environment_override(self):
        with patch.dict(os.environ, {"ENVIRONMENT": "staging"}):
            s = WorkerSettings()
            assert s.environment == "staging"

    def test_minio_override(self):
        with patch.dict(os.environ, {
            "MINIO_ENDPOINT": "minio:9000",
            "MINIO_ACCESS_KEY": "mykey",
            "MINIO_SECRET_KEY": "mysecret",
            "MINIO_SECURE": "true",
        }):
            s = WorkerSettings()
            assert s.minio_endpoint == "minio:9000"
            assert s.minio_access_key == "mykey"
            assert s.minio_secret_key == "mysecret"
            assert s.minio_secure is True

    def test_drive_bucket_override(self):
        with patch.dict(os.environ, {"DRIVE_S3_BUCKET": "custom-bucket"}):
            s = WorkerSettings()
            assert s.drive_s3_bucket == "custom-bucket"

    def test_caption_fields_override(self):
        with patch.dict(os.environ, {
            "SCENE_CAPTION_ENABLED": "true",
            "CAPTION_ENGINE": "florence2",
            "DRIVE_CAPTION_CONCURRENCY": "4",
        }):
            s = WorkerSettings()
            assert s.scene_caption_enabled is True
            assert s.caption_engine == "florence2"
            assert s.drive_caption_concurrency == 4


class TestGetWorkerSettings:
    """Verify the cached singleton factory."""

    def test_returns_worker_settings_instance(self):
        get_worker_settings.cache_clear()
        result = get_worker_settings()
        assert isinstance(result, WorkerSettings)

    def test_caching(self):
        get_worker_settings.cache_clear()
        a = get_worker_settings()
        b = get_worker_settings()
        assert a is b
