"""Tests for render task orchestration (Task 09).

All tests mock external dependencies (pipelines, API, S3).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from heimdex_media_contracts.composition import CompositionSpec
from src.message_adapter import RenderJobMessage
from src.tasks.render import (
    _download_media,
    _report_status,
    _upload_rendered_file,
    process_render_job,
)
import src.tasks.render as render_module


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def render_job() -> RenderJobMessage:
    return RenderJobMessage(
        job_id="job-001",
        org_id="org-001",
        input_spec={
            "output": {"width": 405, "height": 720, "fps": 30, "format": "mp4", "background_color": "#000000"},
            "scene_clips": [
                {
                    "scene_id": "s001",
                    "video_id": "gd_vid1",
                    "source_type": "gdrive",
                    "start_ms": 0,
                    "end_ms": 10000,
                    "timeline_start_ms": 0,
                },
            ],
            "subtitles": [],
        },
    )


@pytest.fixture
def two_clip_render_job() -> RenderJobMessage:
    return RenderJobMessage(
        job_id="job-002",
        org_id="org-001",
        input_spec={
            "output": {"width": 405, "height": 720, "fps": 30, "format": "mp4", "background_color": "#000000"},
            "scene_clips": [
                {
                    "scene_id": "s001",
                    "video_id": "gd_vid1",
                    "source_type": "gdrive",
                    "start_ms": 0,
                    "end_ms": 10000,
                    "timeline_start_ms": 0,
                },
                {
                    "scene_id": "s002",
                    "video_id": "gd_vid2",
                    "source_type": "gdrive",
                    "start_ms": 5000,
                    "end_ms": 15000,
                    "timeline_start_ms": 10000,
                },
            ],
            "subtitles": [],
        },
    )


@pytest.fixture
def mock_api_client():
    client = MagicMock()
    client.base_url = "http://api:8000"
    client._session = MagicMock()
    # Default: PUT status returns 200
    put_resp = MagicMock()
    put_resp.raise_for_status = MagicMock()
    client._session.put.return_value = put_resp
    # Default: GET media-source returns gdrive proxy
    get_resp = MagicMock()
    get_resp.raise_for_status = MagicMock()
    get_resp.json.return_value = {
        "video_id": "gd_vid1",
        "source_type": "gdrive",
        "proxy_s3_key": "org-001/gd_vid1/proxy.mp4",
    }
    client._session.get.return_value = get_resp
    return client


@pytest.fixture
def mock_settings():
    settings = MagicMock()
    settings.drive_s3_bucket = "heimdex-drive"
    settings.use_gpu = False
    return settings


@dataclass
class FakeRenderResult:
    output_path: str = "/tmp/output.mp4"
    duration_ms: int = 10000
    size_bytes: int = 1024000
    render_time_ms: int = 5000


# ---------------------------------------------------------------------------
# _report_status tests
# ---------------------------------------------------------------------------

class TestReportStatus:
    def test_report_rendering(self, mock_api_client: MagicMock) -> None:
        _report_status(mock_api_client, "org-001", "job-001", status="rendering")

        mock_api_client._session.put.assert_called_once()
        call_kwargs = mock_api_client._session.put.call_args
        assert "/internal/shorts-render/job-001/status" in call_kwargs[0][0]
        assert call_kwargs[1]["json"]["status"] == "rendering"
        assert call_kwargs[1]["headers"]["X-Heimdex-Org-Id"] == "org-001"

    def test_report_completed_with_metadata(self, mock_api_client: MagicMock) -> None:
        _report_status(
            mock_api_client, "org-001", "job-001",
            status="completed",
            output_s3_key="shorts-render/org-001/job-001/output.mp4",
            output_duration_ms=10000,
            output_size_bytes=1024000,
            render_time_ms=5000,
        )

        payload = mock_api_client._session.put.call_args[1]["json"]
        assert payload["status"] == "completed"
        assert payload["output_s3_key"] == "shorts-render/org-001/job-001/output.mp4"
        assert payload["output_duration_ms"] == 10000

    def test_report_failed_truncates_error(self, mock_api_client: MagicMock) -> None:
        long_error = "x" * 3000
        _report_status(mock_api_client, "org-001", "job-001", status="failed", error=long_error)

        payload = mock_api_client._session.put.call_args[1]["json"]
        assert len(payload["error"]) == 2000


# ---------------------------------------------------------------------------
# _download_media tests
# ---------------------------------------------------------------------------

class TestDownloadMedia:
    def test_gdrive_download(self, mock_api_client: MagicMock, tmp_path: Path) -> None:
        mock_s3 = MagicMock()

        result = _download_media(
            mock_api_client, mock_s3, "org-001", "gd_vid1", str(tmp_path),
        )

        # Verify API call
        get_call = mock_api_client._session.get.call_args
        assert "/internal/shorts-render/gd_vid1/media-source" in get_call[0][0]
        assert get_call[1]["headers"]["X-Heimdex-Org-Id"] == "org-001"

        # Verify S3 download
        mock_s3.download_file.assert_called_once_with(
            "org-001/gd_vid1/proxy.mp4",
            tmp_path / "gd_vid1.mp4",
        )

        assert result == str(tmp_path / "gd_vid1.mp4")

    def test_unsupported_source_type(self, mock_api_client: MagicMock, tmp_path: Path) -> None:
        get_resp = MagicMock()
        get_resp.raise_for_status = MagicMock()
        get_resp.json.return_value = {
            "video_id": "yt_vid1",
            "source_type": "youtube",
        }
        mock_api_client._session.get.return_value = get_resp

        with pytest.raises(ValueError, match="Unsupported source type"):
            _download_media(mock_api_client, MagicMock(), "org-001", "yt_vid1", str(tmp_path))

    def test_missing_proxy_s3_key(self, mock_api_client: MagicMock, tmp_path: Path) -> None:
        get_resp = MagicMock()
        get_resp.raise_for_status = MagicMock()
        get_resp.json.return_value = {
            "video_id": "gd_vid1",
            "source_type": "gdrive",
            "proxy_s3_key": None,
        }
        mock_api_client._session.get.return_value = get_resp

        with pytest.raises(ValueError, match="No proxy S3 key"):
            _download_media(mock_api_client, MagicMock(), "org-001", "gd_vid1", str(tmp_path))


# ---------------------------------------------------------------------------
# _upload_rendered_file tests
# ---------------------------------------------------------------------------

class TestUploadRenderedFile:
    def test_upload_s3_key_convention(self, tmp_path: Path) -> None:
        output_file = tmp_path / "output.mp4"
        output_file.write_bytes(b"fake mp4 content")

        mock_s3 = MagicMock()
        s3_key, file_size = _upload_rendered_file(
            mock_s3, str(output_file), "org-001", "job-001",
        )

        assert s3_key == "org-001/shorts/renders/job-001/output.mp4"
        assert file_size == len(b"fake mp4 content")
        mock_s3.upload_file.assert_called_once_with(
            output_file, s3_key, content_type="video/mp4",
        )


# ---------------------------------------------------------------------------
# process_render_job tests
# ---------------------------------------------------------------------------

class TestProcessRenderJob:
    """Tests for the full orchestration function.

    We set module-level globals directly and mock _ensure_imports as no-op,
    then patch helper functions and render_composition.
    """

    @pytest.fixture(autouse=True)
    def _setup_module_globals(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Set module globals so process_render_job can use them without real imports."""
        monkeypatch.setattr(render_module, "_ensure_imports", lambda: None)
        monkeypatch.setattr(render_module, "CompositionSpec", CompositionSpec)

    @patch.object(render_module, "render_composition")
    @patch.object(render_module, "S3Client")
    @patch.object(render_module, "_upload_rendered_file")
    @patch.object(render_module, "_download_media")
    @patch.object(render_module, "_report_status")
    def test_happy_path_calls_render_composition(
        self,
        mock_report: MagicMock,
        mock_download: MagicMock,
        mock_upload: MagicMock,
        mock_s3_cls: MagicMock,
        mock_render: MagicMock,
        render_job: RenderJobMessage,
        mock_api_client: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        mock_download.return_value = "/tmp/gd_vid1.mp4"
        mock_render.return_value = FakeRenderResult()
        mock_upload.return_value = ("shorts-render/org-001/job-001/output.mp4", 1024000)

        process_render_job(
            api_client=mock_api_client,
            settings=mock_settings,
            render_job=render_job,
        )

        mock_render.assert_called_once()
        call_kwargs = mock_render.call_args[1]
        assert call_kwargs["media_paths"] == {"gd_vid1": "/tmp/gd_vid1.mp4"}
        assert call_kwargs["use_gpu"] is False

    @patch.object(render_module, "render_composition")
    @patch.object(render_module, "S3Client")
    @patch.object(render_module, "_upload_rendered_file")
    @patch.object(render_module, "_download_media")
    @patch.object(render_module, "_report_status")
    def test_reports_rendering_first(
        self,
        mock_report: MagicMock,
        mock_download: MagicMock,
        mock_upload: MagicMock,
        mock_s3_cls: MagicMock,
        mock_render: MagicMock,
        render_job: RenderJobMessage,
        mock_api_client: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        mock_download.return_value = "/tmp/gd_vid1.mp4"
        mock_render.return_value = FakeRenderResult()
        mock_upload.return_value = ("s3key", 1024)

        process_render_job(
            api_client=mock_api_client,
            settings=mock_settings,
            render_job=render_job,
        )

        first_call = mock_report.call_args_list[0]
        assert first_call[1]["status"] == "rendering"

    @patch.object(render_module, "render_composition")
    @patch.object(render_module, "S3Client")
    @patch.object(render_module, "_upload_rendered_file")
    @patch.object(render_module, "_download_media")
    @patch.object(render_module, "_report_status")
    def test_reports_completed_on_success(
        self,
        mock_report: MagicMock,
        mock_download: MagicMock,
        mock_upload: MagicMock,
        mock_s3_cls: MagicMock,
        mock_render: MagicMock,
        render_job: RenderJobMessage,
        mock_api_client: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        mock_download.return_value = "/tmp/gd_vid1.mp4"
        mock_render.return_value = FakeRenderResult()
        mock_upload.return_value = ("s3key", 1024000)

        process_render_job(
            api_client=mock_api_client,
            settings=mock_settings,
            render_job=render_job,
        )

        last_call = mock_report.call_args_list[-1]
        assert last_call[1]["status"] == "completed"
        assert last_call[1]["output_s3_key"] == "s3key"

    @patch.object(render_module, "render_composition")
    @patch.object(render_module, "S3Client")
    @patch.object(render_module, "_download_media")
    @patch.object(render_module, "_report_status")
    def test_reports_failed_on_pipeline_error(
        self,
        mock_report: MagicMock,
        mock_download: MagicMock,
        mock_s3_cls: MagicMock,
        mock_render: MagicMock,
        render_job: RenderJobMessage,
        mock_api_client: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        mock_download.return_value = "/tmp/gd_vid1.mp4"
        mock_render.side_effect = RuntimeError("ffmpeg crashed")

        process_render_job(
            api_client=mock_api_client,
            settings=mock_settings,
            render_job=render_job,
        )

        last_call = mock_report.call_args_list[-1]
        assert last_call[1]["status"] == "failed"
        assert "ffmpeg crashed" in last_call[1]["error"]

    @patch.object(render_module, "render_composition")
    @patch.object(render_module, "S3Client")
    @patch.object(render_module, "_upload_rendered_file")
    @patch.object(render_module, "_download_media")
    @patch.object(render_module, "_report_status")
    def test_input_spec_parsed_as_composition_spec(
        self,
        mock_report: MagicMock,
        mock_download: MagicMock,
        mock_upload: MagicMock,
        mock_s3_cls: MagicMock,
        mock_render: MagicMock,
        render_job: RenderJobMessage,
        mock_api_client: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        mock_download.return_value = "/tmp/gd_vid1.mp4"
        mock_render.return_value = FakeRenderResult()
        mock_upload.return_value = ("s3key", 1024)

        process_render_job(
            api_client=mock_api_client,
            settings=mock_settings,
            render_job=render_job,
        )

        call_kwargs = mock_render.call_args[1]
        spec = call_kwargs["spec"]
        # Verify it's a real CompositionSpec (parsed from dict)
        assert spec.output.width == 405
        assert spec.output.height == 720
        assert len(spec.scene_clips) == 1

    @patch.object(render_module, "render_composition")
    @patch.object(render_module, "S3Client")
    @patch.object(render_module, "_upload_rendered_file")
    @patch.object(render_module, "_download_media")
    @patch.object(render_module, "_report_status")
    def test_font_dir_from_env(
        self,
        mock_report: MagicMock,
        mock_download: MagicMock,
        mock_upload: MagicMock,
        mock_s3_cls: MagicMock,
        mock_render: MagicMock,
        render_job: RenderJobMessage,
        mock_api_client: MagicMock,
        mock_settings: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("FONT_DIR", "/custom/fonts")
        mock_download.return_value = "/tmp/gd_vid1.mp4"
        mock_render.return_value = FakeRenderResult()
        mock_upload.return_value = ("s3key", 1024)

        process_render_job(
            api_client=mock_api_client,
            settings=mock_settings,
            render_job=render_job,
        )

        assert mock_render.call_args[1]["font_dir"] == "/custom/fonts"

    @patch.object(render_module, "render_composition")
    @patch.object(render_module, "S3Client")
    @patch.object(render_module, "_upload_rendered_file")
    @patch.object(render_module, "_download_media")
    @patch.object(render_module, "_report_status")
    def test_use_gpu_from_settings(
        self,
        mock_report: MagicMock,
        mock_download: MagicMock,
        mock_upload: MagicMock,
        mock_s3_cls: MagicMock,
        mock_render: MagicMock,
        render_job: RenderJobMessage,
        mock_api_client: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        mock_settings.use_gpu = True
        mock_download.return_value = "/tmp/gd_vid1.mp4"
        mock_render.return_value = FakeRenderResult()
        mock_upload.return_value = ("s3key", 1024)

        process_render_job(
            api_client=mock_api_client,
            settings=mock_settings,
            render_job=render_job,
        )

        assert mock_render.call_args[1]["use_gpu"] is True

    @patch.object(render_module, "render_composition")
    @patch.object(render_module, "S3Client")
    @patch.object(render_module, "_upload_rendered_file")
    @patch.object(render_module, "_download_media")
    @patch.object(render_module, "_report_status")
    def test_downloads_each_unique_video(
        self,
        mock_report: MagicMock,
        mock_download: MagicMock,
        mock_upload: MagicMock,
        mock_s3_cls: MagicMock,
        mock_render: MagicMock,
        two_clip_render_job: RenderJobMessage,
        mock_api_client: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        mock_download.side_effect = ["/tmp/gd_vid1.mp4", "/tmp/gd_vid2.mp4"]
        mock_render.return_value = FakeRenderResult()
        mock_upload.return_value = ("s3key", 1024)

        process_render_job(
            api_client=mock_api_client,
            settings=mock_settings,
            render_job=two_clip_render_job,
        )

        assert mock_download.call_count == 2
        video_ids = [c[0][3] for c in mock_download.call_args_list]
        assert "gd_vid1" in video_ids
        assert "gd_vid2" in video_ids

    @patch.object(render_module, "render_composition")
    @patch.object(render_module, "S3Client")
    @patch.object(render_module, "_download_media")
    @patch.object(render_module, "_report_status")
    def test_status_update_failure_during_error_handling(
        self,
        mock_report: MagicMock,
        mock_download: MagicMock,
        mock_s3_cls: MagicMock,
        mock_render: MagicMock,
        render_job: RenderJobMessage,
        mock_api_client: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        """If reporting 'failed' also fails, the job should still not crash."""
        mock_download.return_value = "/tmp/gd_vid1.mp4"
        mock_render.side_effect = RuntimeError("ffmpeg crashed")
        # First call (rendering) succeeds, second call (failed) raises
        mock_report.side_effect = [None, RuntimeError("API down")]

        # Should not raise — error is logged, not propagated
        process_render_job(
            api_client=mock_api_client,
            settings=mock_settings,
            render_job=render_job,
        )

        assert mock_report.call_count == 2

    @patch.object(render_module, "render_composition")
    @patch.object(render_module, "S3Client")
    @patch.object(render_module, "_upload_rendered_file")
    @patch.object(render_module, "_download_media")
    @patch.object(render_module, "_report_status")
    def test_cleanup_temp_dir(
        self,
        mock_report: MagicMock,
        mock_download: MagicMock,
        mock_upload: MagicMock,
        mock_s3_cls: MagicMock,
        mock_render: MagicMock,
        render_job: RenderJobMessage,
        mock_api_client: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        """Temp directory should be cleaned up after render."""
        mock_download.return_value = "/tmp/gd_vid1.mp4"
        mock_render.return_value = FakeRenderResult()
        mock_upload.return_value = ("s3key", 1024)

        with patch("src.tasks.render.shutil.rmtree") as mock_rmtree:
            process_render_job(
                api_client=mock_api_client,
                settings=mock_settings,
                render_job=render_job,
            )

            mock_rmtree.assert_called_once()
            assert mock_rmtree.call_args[1].get("ignore_errors") is True


# ---------------------------------------------------------------------------
# _check_job_alive — pre-render liveness probe
# ---------------------------------------------------------------------------

from src.tasks.render import _check_job_alive  # noqa: E402


def _make_resp(status_code: int) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    return resp


class TestCheckJobAlive:
    def test_returns_true_on_200(self, mock_api_client: MagicMock) -> None:
        mock_api_client._session.get.return_value = _make_resp(200)
        assert _check_job_alive(mock_api_client, "job-1") is True
        # Hits the /exists path, not /status or /media-source.
        called_url = mock_api_client._session.get.call_args[0][0]
        assert "/internal/shorts-render/job-1/exists" in called_url

    def test_returns_false_on_404(self, mock_api_client: MagicMock) -> None:
        # 404 is the row-deleted signal — the only path that
        # legitimately tells the worker to skip.
        mock_api_client._session.get.return_value = _make_resp(404)
        assert _check_job_alive(mock_api_client, "job-1") is False

    def test_fails_open_on_5xx(self, mock_api_client: MagicMock) -> None:
        # api hiccup → over-render rather than silently drop the job.
        mock_api_client._session.get.return_value = _make_resp(503)
        assert _check_job_alive(mock_api_client, "job-1") is True

    def test_fails_open_on_transport_exception(
        self, mock_api_client: MagicMock,
    ) -> None:
        # Network blip mid-poll: the worker still proceeds with the
        # render. The api's idempotent ``complete_idempotent``
        # absorbs a duplicate completion if the row WAS deleted but
        # the probe couldn't reach it in time.
        mock_api_client._session.get.side_effect = Exception("connection reset")
        assert _check_job_alive(mock_api_client, "job-1") is True


# ---------------------------------------------------------------------------
# process_render_job integration — skip path on deleted row
# ---------------------------------------------------------------------------


@patch("src.tasks.render._upload_rendered_file")
@patch("src.tasks.render._download_media")
@patch("src.tasks.render._report_status")
def test_process_render_job_skips_when_row_deleted(
    mock_report: MagicMock,
    mock_download: MagicMock,
    mock_upload: MagicMock,
    render_job: RenderJobMessage,
    mock_api_client: MagicMock,
    mock_settings: MagicMock,
) -> None:
    """When the alive probe 404s, the render path must short-circuit
    BEFORE any S3 download, ffmpeg invocation, or status PUT — the
    SQS message is removed via normal task-success ack and the
    deleted row stays gone.
    """
    # Route GETs by URL: /exists → 404, anything else → default.
    default_get = mock_api_client._session.get.return_value

    def _routed_get(url, **kwargs):
        if "/exists" in url:
            return _make_resp(404)
        return default_get

    mock_api_client._session.get.side_effect = _routed_get

    process_render_job(
        api_client=mock_api_client,
        settings=mock_settings,
        render_job=render_job,
    )

    # No work should have happened past the probe.
    mock_report.assert_not_called()
    mock_download.assert_not_called()
    mock_upload.assert_not_called()


# NOTE: a corresponding "proceeds when row alive" integration test
# would need the full ``_ensure_imports`` path (heimdex_media_pipelines
# + heimdex_media_contracts) which isn't installed in the api venv
# used by the local pytest sweep. The existing
# ``TestProcessRenderJob`` tests above cover the proceed path
# (running in the worker container with the full ML stack), and
# the alive-probe is exercised in the unit tests above.
