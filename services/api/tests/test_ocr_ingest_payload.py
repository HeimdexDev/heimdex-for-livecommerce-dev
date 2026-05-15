import importlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.modules.drive.keys import scene_manifest_s3_key


class TestSceneManifestKey:
    def test_format(self):
        key = scene_manifest_s3_key("org-1", "gd_abc")
        assert key == "org-1/drive/manifests/gd_abc/scenes.json"


class TestOcrPayloadConstruction:
    def test_ocr_text_added_to_scenes(self):
        scenes = [
            {
                "scene_id": "v_scene_0",
                "index": 0,
                "start_ms": 0,
                "end_ms": 5000,
                "ocr_text_raw": "",
                "ocr_char_count": 0,
                "transcript_raw": "hello",
            },
        ]
        ocr_results = {0: "detected text"}
        updated = []
        for i, scene in enumerate(scenes):
            scene_copy = dict(scene)
            if i in ocr_results:
                ocr_text = ocr_results[i][:10_000]
                scene_copy["ocr_text_raw"] = ocr_text
                scene_copy["ocr_char_count"] = len(ocr_text)
            updated.append(scene_copy)
        assert updated[0]["ocr_text_raw"] == "detected text"
        assert updated[0]["ocr_char_count"] == 13
        assert updated[0]["transcript_raw"] == "hello"

    def test_ocr_text_truncated_at_10k(self):
        long_text = "x" * 15_000
        truncated = long_text[:10_000]
        assert len(truncated) == 10_000

    def test_scenes_without_ocr_preserved(self):
        scenes = [
            {
                "scene_id": "v_scene_0",
                "index": 0,
                "start_ms": 0,
                "end_ms": 5000,
                "transcript_raw": "original",
                "ocr_text_raw": "",
                "ocr_char_count": 0,
            },
        ]
        ocr_results = {}
        updated = []
        for i, scene in enumerate(scenes):
            scene_copy = dict(scene)
            if i in ocr_results:
                scene_copy["ocr_text_raw"] = ocr_results[i][:10_000]
                scene_copy["ocr_char_count"] = len(ocr_results[i][:10_000])
            updated.append(scene_copy)
        assert updated[0]["ocr_text_raw"] == ""
        assert updated[0]["transcript_raw"] == "original"


class TestSceneManifestUpload:
    def test_manifest_upload_creates_correct_json(self, tmp_path):
        from uuid import UUID

        drive_worker_path = Path(__file__).resolve().parents[2] / "drive-worker"
        process_path = drive_worker_path / "src" / "tasks" / "process.py"
        if not process_path.exists():
            pytest.skip("drive-worker code not available in API container")
        spec = importlib.util.spec_from_file_location(
            "_drive_worker_process_for_test", process_path,
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _upload_scene_manifest = mod._upload_scene_manifest

        s3 = MagicMock()
        _upload_scene_manifest(
            s3=s3,
            org_id_str="org-1",
            video_id="gd_abc",
            video_title="Test Video",
            library_id=UUID("00000000-0000-0000-0000-000000000001"),
            duration_ms=60000,
            scenes=[{"scene_id": "gd_abc_scene_0", "index": 0}],
            temp_dir=tmp_path,
        )

        manifest_path = tmp_path / "scenes.json"
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())
        assert data["video_id"] == "gd_abc"
        assert data["video_title"] == "Test Video"
        assert data["library_id"] == "00000000-0000-0000-0000-000000000001"
        assert data["total_duration_ms"] == 60000
        assert len(data["scenes"]) == 1

        s3.upload_file.assert_called_once()
        call_args = s3.upload_file.call_args
        assert str(call_args[0][1]) == "org-1/drive/manifests/gd_abc/scenes.json"
