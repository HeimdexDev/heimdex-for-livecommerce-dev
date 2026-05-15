# pyright: reportAttributeAccessIssue=false, reportMissingParameterType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false, reportUnknownMemberType=false, reportUnknownParameterType=false, reportUnknownVariableType=false, reportAny=false, reportUnannotatedClassAttribute=false, reportUnusedParameter=false

import importlib.util
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "drive-worker" / "src"))
sys.path.insert(0, str(ROOT / "services" / "worker_sdk" / "src"))

process_path = ROOT / "services" / "drive-worker" / "src" / "tasks" / "process.py"
spec = importlib.util.spec_from_file_location("drive_worker_process", process_path)
assert spec and spec.loader
process = importlib.util.module_from_spec(spec)
spec.loader.exec_module(process)


def _make_claimed_file(mime_type: str = "image/jpeg") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        org_id=uuid4(),
        connection_id=uuid4(),
        google_file_id="google-file-1",
        file_name="sample.jpg",
        video_id="gd_test123",
        mime_type=mime_type,
        md5_checksum="md5",
        file_size_bytes=123,
        drive_path="Folder/sample.jpg",
        web_view_link="https://drive.google.com/file/d/google-file-1/view",
        library_id=uuid4(),
        scope_type="drive",
        drive_id="drive-1",
        google_created_time="2026-03-01T00:00:00Z",
        google_modified_time="2026-03-01T00:00:00Z",
        lease_token="lease-token-1",
        lease_expires_at=None,
    )


def _make_settings(tmp_path: Path, mode: str = "cpu") -> SimpleNamespace:
    return SimpleNamespace(
        drive_temp_dir=str(tmp_path),
        drive_temp_disk_budget_gb=1,
        drive_s3_bucket="test-bucket",
        drive_api_base_url="http://localhost:8000",
        drive_internal_api_key="internal-key",
        drive_transcode_mode=mode,
    )


def _install_image_sdk_stubs(monkeypatch: pytest.MonkeyPatch, upload_calls: list[tuple[str, str]]) -> None:
    drive_keys = types.ModuleType("heimdex_worker_sdk.drive_keys")
    drive_keys.audio_s3_key = lambda org_id, video_id: f"{org_id}/audio/{video_id}.wav"
    drive_keys.proxy_s3_key = lambda org_id, drive_id, google_file_id: f"{org_id}/proxy/{drive_id}/{google_file_id}.mp4"
    drive_keys.thumbnail_s3_key = lambda org_id, video_id, scene_id: f"{org_id}/thumb/{video_id}/{scene_id}.jpg"
    drive_keys.thumbnail_s3_prefix = lambda org_id, video_id: f"{org_id}/thumb/{video_id}/"
    drive_keys.enrichment_keyframe_s3_key = (
        lambda org_id, video_id, scene_id: f"{org_id}/keyframe/{video_id}/{scene_id}.jpg"
    )
    drive_keys.enrichment_keyframe_s3_prefix = lambda org_id, video_id: f"{org_id}/keyframe/{video_id}/"
    monkeypatch.setitem(sys.modules, "heimdex_worker_sdk.drive_keys", drive_keys)

    s3_module = types.ModuleType("heimdex_worker_sdk.s3")

    class FakeS3Client:
        def __init__(self, bucket: str):
            self.bucket = bucket

        def ensure_bucket(self) -> None:
            return None

        def upload_file(self, local_path: Path, s3_key: str, content_type: str | None = None, tags=None) -> None:
            upload_calls.append((str(local_path), s3_key))

    s3_module.S3Client = FakeS3Client
    monkeypatch.setitem(sys.modules, "heimdex_worker_sdk.s3", s3_module)


def _install_video_pipeline_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline_pkg = types.ModuleType("heimdex_media_pipelines")
    transcoding_mod = types.ModuleType("heimdex_media_pipelines.transcoding")
    detector_mod = types.ModuleType("heimdex_media_pipelines.scenes.detector")
    keyframe_mod = types.ModuleType("heimdex_media_pipelines.scenes.keyframe")
    assembler_mod = types.ModuleType("heimdex_media_pipelines.scenes.assembler")
    scenes_pkg = types.ModuleType("heimdex_media_pipelines.scenes")

    transcoding_mod.probe_video = lambda *_args, **_kwargs: SimpleNamespace(
        duration_ms=1000,
        frame_rate=29.97,
        width=1920,
        height=1080,
    )
    transcoding_mod.make_transcode_decision = (
        lambda *_args, **_kwargs: SimpleNamespace(should_transcode=False, reason="already_ok")
    )
    transcoding_mod.transcode_to_proxy = lambda *_args, **_kwargs: None
    detector_mod.detect_scenes = lambda *_args, **_kwargs: []
    keyframe_mod.extract_all_keyframes = lambda *_args, **_kwargs: []
    assembler_mod.assemble_scenes = lambda *_args, **_kwargs: SimpleNamespace(scenes=[])

    monkeypatch.setitem(sys.modules, "heimdex_media_pipelines", pipeline_pkg)
    monkeypatch.setitem(sys.modules, "heimdex_media_pipelines.transcoding", transcoding_mod)
    monkeypatch.setitem(sys.modules, "heimdex_media_pipelines.scenes", scenes_pkg)
    monkeypatch.setitem(sys.modules, "heimdex_media_pipelines.scenes.detector", detector_mod)
    monkeypatch.setitem(sys.modules, "heimdex_media_pipelines.scenes.keyframe", keyframe_mod)
    monkeypatch.setitem(sys.modules, "heimdex_media_pipelines.scenes.assembler", assembler_mod)


def test_process_image_routing(tmp_path, monkeypatch):
    api_client = MagicMock()
    claimed_file = _make_claimed_file(mime_type="image/jpeg")
    settings = _make_settings(tmp_path)

    mock_process_image = MagicMock()
    monkeypatch.setattr(process, "_process_image", mock_process_image)

    process._process_single_file(api_client=api_client, settings=settings, claimed_file=claimed_file)

    mock_process_image.assert_called_once_with(api_client, settings, claimed_file)


def test_process_video_routing(tmp_path, monkeypatch):
    api_client = MagicMock()
    api_client.get_drive_token.return_value = SimpleNamespace(access_token="token")
    claimed_file = _make_claimed_file(mime_type="video/mp4")
    settings = _make_settings(tmp_path, mode="gpu")

    upload_calls: list[tuple[str, str]] = []
    _install_image_sdk_stubs(monkeypatch, upload_calls)
    _install_video_pipeline_stubs(monkeypatch)

    monkeypatch.setattr(process, "_build_drive_service", lambda _token: MagicMock())
    monkeypatch.setattr(process, "_download_file", lambda **kwargs: kwargs["dest_path"].write_bytes(b"video-data"))

    mock_process_image = MagicMock()
    mock_handle_gpu_mode = MagicMock()
    monkeypatch.setattr(process, "_process_image", mock_process_image)
    monkeypatch.setattr(process, "_handle_gpu_mode", mock_handle_gpu_mode)

    process._process_single_file(api_client=api_client, settings=settings, claimed_file=claimed_file)

    mock_process_image.assert_not_called()
    mock_handle_gpu_mode.assert_called_once()


def test_process_image_creates_single_scene(tmp_path, monkeypatch):
    api_client = MagicMock()
    api_client.get_drive_token.return_value = SimpleNamespace(access_token="token")
    claimed_file = _make_claimed_file(mime_type="image/jpeg")
    settings = _make_settings(tmp_path)

    upload_calls: list[tuple[str, str]] = []
    _install_image_sdk_stubs(monkeypatch, upload_calls)

    monkeypatch.setattr(process, "_build_drive_service", lambda _token: MagicMock())
    monkeypatch.setattr(
        process,
        "_download_file",
        lambda **kwargs: kwargs["dest_path"].write_text(
            json.dumps({"size": [1920, 1080], "format": "JPEG"}),
            encoding="utf-8",
        ),
    )
    post_scenes_mock = MagicMock(return_value={"indexed_count": 1})
    monkeypatch.setattr(process, "_post_scenes_to_api", post_scenes_mock)

    process._process_image(api_client=api_client, settings=settings, claimed_file=claimed_file)

    post_scenes_mock.assert_called_once()
    scenes = post_scenes_mock.call_args.kwargs["scenes"]
    assert len(scenes) == 1
    scene = scenes[0]
    assert scene["scene_id"] == f"{claimed_file.video_id}_scene_000"
    assert scene["content_type"] == "image"
    assert scene["start_ms"] == 0
    assert scene["end_ms"] == 0


def test_process_image_uploads_to_s3(tmp_path, monkeypatch):
    api_client = MagicMock()
    api_client.get_drive_token.return_value = SimpleNamespace(access_token="token")
    claimed_file = _make_claimed_file(mime_type="image/jpeg")
    settings = _make_settings(tmp_path)

    upload_calls: list[tuple[str, str]] = []
    _install_image_sdk_stubs(monkeypatch, upload_calls)

    monkeypatch.setattr(process, "_build_drive_service", lambda _token: MagicMock())
    monkeypatch.setattr(
        process,
        "_download_file",
        lambda **kwargs: kwargs["dest_path"].write_text(
            json.dumps({"size": [1920, 1080], "format": "JPEG"}),
            encoding="utf-8",
        ),
    )
    monkeypatch.setattr(process, "_post_scenes_to_api", MagicMock(return_value={"indexed_count": 1}))

    process._process_image(api_client=api_client, settings=settings, claimed_file=claimed_file)

    assert len(upload_calls) == 2
    uploaded_keys = [key for _, key in upload_calls]
    assert any("thumb" in key for key in uploaded_keys)
    assert any("keyframe" in key for key in uploaded_keys)


def test_process_image_updates_status_indexed(tmp_path, monkeypatch):
    api_client = MagicMock()
    api_client.get_drive_token.return_value = SimpleNamespace(access_token="token")
    claimed_file = _make_claimed_file(mime_type="image/jpeg")
    settings = _make_settings(tmp_path)

    upload_calls: list[tuple[str, str]] = []
    _install_image_sdk_stubs(monkeypatch, upload_calls)

    monkeypatch.setattr(process, "_build_drive_service", lambda _token: MagicMock())
    monkeypatch.setattr(
        process,
        "_download_file",
        lambda **kwargs: kwargs["dest_path"].write_text(
            json.dumps({"size": [1920, 1080], "format": "JPEG"}),
            encoding="utf-8",
        ),
    )
    monkeypatch.setattr(process, "_post_scenes_to_api", MagicMock(return_value={"indexed_count": 1}))

    process._process_image(api_client=api_client, settings=settings, claimed_file=claimed_file)

    indexed_calls = [
        call for call in api_client.update_processing_status.call_args_list if call.kwargs.get("status") == "indexed"
    ]
    assert len(indexed_calls) == 1
    kwargs = indexed_calls[0].kwargs
    assert kwargs["scene_count"] == 1
    assert kwargs["audio_s3_key"] is None


def test_process_image_failure_sets_failed_status(tmp_path, monkeypatch):
    api_client = MagicMock()
    api_client.get_drive_token.return_value = SimpleNamespace(access_token="token")
    claimed_file = _make_claimed_file(mime_type="image/jpeg")
    settings = _make_settings(tmp_path)

    upload_calls: list[tuple[str, str]] = []
    _install_image_sdk_stubs(monkeypatch, upload_calls)

    monkeypatch.setattr(process, "_build_drive_service", lambda _token: MagicMock())

    def _raise_download(**_kwargs):
        raise RuntimeError("download failed")

    monkeypatch.setattr(process, "_download_file", _raise_download)

    with pytest.raises(RuntimeError):
        process._process_image(api_client=api_client, settings=settings, claimed_file=claimed_file)

    failed_calls = [
        call for call in api_client.update_processing_status.call_args_list if call.kwargs.get("status") == "failed"
    ]
    assert len(failed_calls) == 1
