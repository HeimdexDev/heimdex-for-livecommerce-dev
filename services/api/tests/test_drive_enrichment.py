import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "drive-worker"))

_process = pytest.importorskip(
    "src.tasks.process",
    reason="drive-worker code not available in API container",
)


def _make_scene_doc(scene_id: str, thumbnail_path: str = None):
    return SimpleNamespace(
        scene_id=scene_id,
        thumbnail_path=thumbnail_path,
    )


def _make_scene_result(scenes):
    return SimpleNamespace(scenes=scenes)


class TestUploadEnrichmentArtifactsDisabled:
    def test_returns_empty_when_disabled(self, tmp_path):
        result = _process._upload_enrichment_artifacts(
            s3=MagicMock(),
            original_path=tmp_path / "video.mp4",
            scene_result=_make_scene_result([]),
            org_id_str="org-1",
            video_id="gd_abc",
            temp_dir=tmp_path,
            enabled=False,
        )
        assert result == {}

    def test_no_s3_calls_when_disabled(self, tmp_path):
        s3 = MagicMock()
        _process._upload_enrichment_artifacts(
            s3=s3,
            original_path=tmp_path / "video.mp4",
            scene_result=_make_scene_result([_make_scene_doc("s_000")]),
            org_id_str="org-1",
            video_id="gd_abc",
            temp_dir=tmp_path,
            enabled=False,
        )
        s3.upload_file.assert_not_called()


class TestUploadEnrichmentArtifactsEnabled:
    @patch("src.tasks.process.subprocess.run")
    def test_audio_extraction_and_upload(self, mock_run, tmp_path):
        _upload_enrichment_artifacts = _process._upload_enrichment_artifacts

        audio_path = tmp_path / "audio.wav"
        audio_path.write_bytes(b"\x00" * 1024)

        def fake_ffmpeg(*args, **kwargs):
            audio_path.write_bytes(b"\x00" * 2048)
            return subprocess.CompletedProcess(args=[], returncode=0)

        mock_run.side_effect = fake_ffmpeg
        s3 = MagicMock()

        result = _upload_enrichment_artifacts(
            s3=s3,
            original_path=tmp_path / "video.mp4",
            scene_result=_make_scene_result([]),
            org_id_str="org-1",
            video_id="gd_abc",
            temp_dir=tmp_path,
            enabled=True,
        )

        mock_run.assert_called_once()
        ffmpeg_args = mock_run.call_args[0][0]
        assert ffmpeg_args[0] == "ffmpeg"
        assert "-ar" in ffmpeg_args
        assert "16000" in ffmpeg_args
        assert "-ac" in ffmpeg_args
        assert "1" in ffmpeg_args

        assert "audio_s3_key" in result
        assert result["audio_s3_key"] == "org-1/drive/audio/gd_abc/audio.wav"
        assert result["enrichment_state"] == "pending"
        assert result["stt_status"] == "pending"

    @patch("src.tasks.process.subprocess.run")
    def test_keyframe_upload(self, mock_run, tmp_path):
        _upload_enrichment_artifacts = _process._upload_enrichment_artifacts

        mock_run.side_effect = subprocess.CalledProcessError(1, "ffmpeg")

        kf_path = tmp_path / "keyframe.jpg"
        kf_path.write_bytes(b"\xff\xd8\xff")

        scene = _make_scene_doc("gd_abc_scene_000", thumbnail_path=str(kf_path))
        s3 = MagicMock()

        result = _upload_enrichment_artifacts(
            s3=s3,
            original_path=tmp_path / "video.mp4",
            scene_result=_make_scene_result([scene]),
            org_id_str="org-1",
            video_id="gd_abc",
            temp_dir=tmp_path,
            enabled=True,
        )

        assert "keyframe_s3_prefix" in result
        assert result["keyframe_s3_prefix"] == "org-1/drive/keyframes/gd_abc/"
        assert result["enrichment_state"] == "pending"
        assert result["ocr_status"] == "pending"

        upload_calls = s3.upload_file.call_args_list
        assert len(upload_calls) == 1
        uploaded_key = upload_calls[0][0][1]
        assert uploaded_key == "org-1/drive/keyframes/gd_abc/gd_abc_scene_000.jpg"

    @patch("src.tasks.process.subprocess.run")
    def test_both_audio_and_keyframes(self, mock_run, tmp_path):
        _upload_enrichment_artifacts = _process._upload_enrichment_artifacts

        audio_path = tmp_path / "audio.wav"

        def fake_ffmpeg(*args, **kwargs):
            audio_path.write_bytes(b"\x00" * 512)
            return subprocess.CompletedProcess(args=[], returncode=0)

        mock_run.side_effect = fake_ffmpeg

        kf0 = tmp_path / "kf0.jpg"
        kf0.write_bytes(b"\xff\xd8")
        kf1 = tmp_path / "kf1.jpg"
        kf1.write_bytes(b"\xff\xd8")

        scenes = [
            _make_scene_doc("gd_abc_scene_000", str(kf0)),
            _make_scene_doc("gd_abc_scene_001", str(kf1)),
        ]
        s3 = MagicMock()

        result = _upload_enrichment_artifacts(
            s3=s3,
            original_path=tmp_path / "video.mp4",
            scene_result=_make_scene_result(scenes),
            org_id_str="org-1",
            video_id="gd_abc",
            temp_dir=tmp_path,
            enabled=True,
        )

        assert result["enrichment_state"] == "pending"
        assert result["stt_status"] == "pending"
        assert result["ocr_status"] == "pending"
        assert result["audio_s3_key"] == "org-1/drive/audio/gd_abc/audio.wav"
        assert result["keyframe_s3_prefix"] == "org-1/drive/keyframes/gd_abc/"
        assert s3.upload_file.call_count == 3

    @patch("src.tasks.process.subprocess.run")
    def test_no_thumbnail_path_skips_keyframe(self, mock_run, tmp_path):
        _upload_enrichment_artifacts = _process._upload_enrichment_artifacts

        mock_run.side_effect = subprocess.CalledProcessError(1, "ffmpeg")

        scene = _make_scene_doc("gd_abc_scene_000", thumbnail_path=None)
        s3 = MagicMock()

        result = _upload_enrichment_artifacts(
            s3=s3,
            original_path=tmp_path / "video.mp4",
            scene_result=_make_scene_result([scene]),
            org_id_str="org-1",
            video_id="gd_abc",
            temp_dir=tmp_path,
            enabled=True,
        )

        assert result == {}
        s3.upload_file.assert_not_called()

    @patch("src.tasks.process.subprocess.run")
    def test_audio_failure_still_uploads_keyframes(self, mock_run, tmp_path):
        _upload_enrichment_artifacts = _process._upload_enrichment_artifacts

        mock_run.side_effect = subprocess.CalledProcessError(1, "ffmpeg")

        kf_path = tmp_path / "kf.jpg"
        kf_path.write_bytes(b"\xff\xd8")
        scene = _make_scene_doc("gd_abc_scene_000", str(kf_path))
        s3 = MagicMock()

        result = _upload_enrichment_artifacts(
            s3=s3,
            original_path=tmp_path / "video.mp4",
            scene_result=_make_scene_result([scene]),
            org_id_str="org-1",
            video_id="gd_abc",
            temp_dir=tmp_path,
            enabled=True,
        )

        assert "audio_s3_key" not in result
        assert "keyframe_s3_prefix" in result
        assert result["enrichment_state"] == "pending"
        assert result["stt_status"] is None
        assert result["ocr_status"] == "pending"

    @patch("src.tasks.process.subprocess.run")
    def test_keyframe_upload_failure_is_graceful(self, mock_run, tmp_path):
        _upload_enrichment_artifacts = _process._upload_enrichment_artifacts

        mock_run.side_effect = subprocess.CalledProcessError(1, "ffmpeg")

        kf_path = tmp_path / "kf.jpg"
        kf_path.write_bytes(b"\xff\xd8")
        scene = _make_scene_doc("gd_abc_scene_000", str(kf_path))

        s3 = MagicMock()
        s3.upload_file.side_effect = RuntimeError("S3 timeout")

        result = _upload_enrichment_artifacts(
            s3=s3,
            original_path=tmp_path / "video.mp4",
            scene_result=_make_scene_result([scene]),
            org_id_str="org-1",
            video_id="gd_abc",
            temp_dir=tmp_path,
            enabled=True,
        )

        assert result == {}

    @patch("src.tasks.process.subprocess.run")
    def test_ffmpeg_command_format(self, mock_run, tmp_path):
        _upload_enrichment_artifacts = _process._upload_enrichment_artifacts

        audio_path = tmp_path / "audio.wav"

        def fake_ffmpeg(*args, **kwargs):
            audio_path.write_bytes(b"\x00" * 100)
            return subprocess.CompletedProcess(args=[], returncode=0)

        mock_run.side_effect = fake_ffmpeg
        s3 = MagicMock()

        _upload_enrichment_artifacts(
            s3=s3,
            original_path=tmp_path / "video.mp4",
            scene_result=_make_scene_result([]),
            org_id_str="org-1",
            video_id="gd_abc",
            temp_dir=tmp_path,
            enabled=True,
        )

        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert cmd == [
            "ffmpeg", "-i", str(tmp_path / "video.mp4"),
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            "-y", str(tmp_path / "audio.wav"),
        ]
        assert call_args[1]["capture_output"] is True
        assert call_args[1]["check"] is True
        assert call_args[1]["timeout"] == 600
