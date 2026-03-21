"""Tests for render event logging in the worker."""

import logging
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from heimdex_media_contracts.composition import CompositionSpec
from src.message_adapter import RenderJobMessage
from src.tasks.render import process_render_job
import src.tasks.render as render_module


@dataclass
class FakeRenderResult:
    output_path: str = "/tmp/output.mp4"
    duration_ms: int = 10000
    size_bytes: int = 1024000
    render_time_ms: int = 5000


@pytest.fixture
def render_job() -> RenderJobMessage:
    return RenderJobMessage(
        job_id="job-001",
        org_id="org-001",
        input_spec={
            "output": {"width": 405, "height": 720, "fps": 30, "format": "mp4", "background_color": "#000000"},
            "scene_clips": [
                {"scene_id": "s001", "video_id": "gd_vid1", "source_type": "gdrive",
                 "start_ms": 0, "end_ms": 10000, "timeline_start_ms": 0},
            ],
            "subtitles": [
                {"text": "테스트", "start_ms": 0, "end_ms": 5000},
            ],
        },
    )


@pytest.fixture
def mock_api_client():
    client = MagicMock()
    client.base_url = "http://api:8000"
    client._session = MagicMock()
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    client._session.put.return_value = resp
    client._session.get.return_value = resp
    return client


@pytest.fixture
def mock_settings():
    settings = MagicMock()
    settings.drive_s3_bucket = "heimdex-drive"
    settings.use_gpu = False
    return settings


@pytest.fixture(autouse=True)
def _setup_module_globals(monkeypatch):
    monkeypatch.setattr(render_module, "_ensure_imports", lambda: None)
    monkeypatch.setattr(render_module, "CompositionSpec", CompositionSpec)


class TestWorkerRenderLogging:
    @patch.object(render_module, "render_composition")
    @patch.object(render_module, "S3Client")
    @patch.object(render_module, "_upload_rendered_file")
    @patch.object(render_module, "_download_media")
    @patch.object(render_module, "_report_status")
    def test_render_started_log(
        self, mock_report, mock_download, mock_upload, mock_s3_cls,
        mock_render, render_job, mock_api_client, mock_settings, caplog,
    ) -> None:
        mock_download.return_value = "/tmp/gd_vid1.mp4"
        mock_render.return_value = FakeRenderResult()
        mock_upload.return_value = ("s3key", 1024)

        with caplog.at_level(logging.INFO):
            process_render_job(api_client=mock_api_client, settings=mock_settings, render_job=render_job)

        assert any("render_started" in r.message for r in caplog.records)

    @patch.object(render_module, "render_composition")
    @patch.object(render_module, "S3Client")
    @patch.object(render_module, "_upload_rendered_file")
    @patch.object(render_module, "_download_media")
    @patch.object(render_module, "_report_status")
    def test_clip_extracted_log(
        self, mock_report, mock_download, mock_upload, mock_s3_cls,
        mock_render, render_job, mock_api_client, mock_settings, caplog,
    ) -> None:
        mock_download.return_value = "/tmp/gd_vid1.mp4"
        mock_render.return_value = FakeRenderResult()
        mock_upload.return_value = ("s3key", 1024)

        with caplog.at_level(logging.INFO):
            process_render_job(api_client=mock_api_client, settings=mock_settings, render_job=render_job)

        assert any("clip_extracted" in r.message for r in caplog.records)

    @patch.object(render_module, "render_composition")
    @patch.object(render_module, "S3Client")
    @patch.object(render_module, "_upload_rendered_file")
    @patch.object(render_module, "_download_media")
    @patch.object(render_module, "_report_status")
    def test_ffmpeg_encode_started_log(
        self, mock_report, mock_download, mock_upload, mock_s3_cls,
        mock_render, render_job, mock_api_client, mock_settings, caplog,
    ) -> None:
        mock_download.return_value = "/tmp/gd_vid1.mp4"
        mock_render.return_value = FakeRenderResult()
        mock_upload.return_value = ("s3key", 1024)

        with caplog.at_level(logging.INFO):
            process_render_job(api_client=mock_api_client, settings=mock_settings, render_job=render_job)

        assert any("ffmpeg_encode_started" in r.message for r in caplog.records)

    @patch.object(render_module, "render_composition")
    @patch.object(render_module, "S3Client")
    @patch.object(render_module, "_upload_rendered_file")
    @patch.object(render_module, "_download_media")
    @patch.object(render_module, "_report_status")
    def test_render_completed_log(
        self, mock_report, mock_download, mock_upload, mock_s3_cls,
        mock_render, render_job, mock_api_client, mock_settings, caplog,
    ) -> None:
        mock_download.return_value = "/tmp/gd_vid1.mp4"
        mock_render.return_value = FakeRenderResult()
        mock_upload.return_value = ("s3key", 1024)

        with caplog.at_level(logging.INFO):
            process_render_job(api_client=mock_api_client, settings=mock_settings, render_job=render_job)

        assert any("render_completed" in r.message for r in caplog.records)

    @patch.object(render_module, "render_composition")
    @patch.object(render_module, "S3Client")
    @patch.object(render_module, "_download_media")
    @patch.object(render_module, "_report_status")
    def test_render_failed_log(
        self, mock_report, mock_download, mock_s3_cls,
        mock_render, render_job, mock_api_client, mock_settings, caplog,
    ) -> None:
        mock_download.return_value = "/tmp/gd_vid1.mp4"
        mock_render.side_effect = RuntimeError("ffmpeg crashed")

        with caplog.at_level(logging.ERROR):
            process_render_job(api_client=mock_api_client, settings=mock_settings, render_job=render_job)

        failed_records = [r for r in caplog.records if "render_failed" in r.message]
        assert len(failed_records) >= 1

    @patch.object(render_module, "render_composition")
    @patch.object(render_module, "S3Client")
    @patch.object(render_module, "_upload_rendered_file")
    @patch.object(render_module, "_download_media")
    @patch.object(render_module, "_report_status")
    def test_all_logs_include_job_id(
        self, mock_report, mock_download, mock_upload, mock_s3_cls,
        mock_render, render_job, mock_api_client, mock_settings, caplog,
    ) -> None:
        mock_download.return_value = "/tmp/gd_vid1.mp4"
        mock_render.return_value = FakeRenderResult()
        mock_upload.return_value = ("s3key", 1024)

        with caplog.at_level(logging.INFO):
            process_render_job(api_client=mock_api_client, settings=mock_settings, render_job=render_job)

        render_logs = [r for r in caplog.records
                       if any(evt in r.message for evt in ("render_started", "clip_extracted", "ffmpeg_encode_started", "render_completed"))]
        assert len(render_logs) >= 4
        for record in render_logs:
            assert "job-001" in str(getattr(record, "job_id", "")) or "job-001" in str(record.__dict__.get("job_id", ""))
