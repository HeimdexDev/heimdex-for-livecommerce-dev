import pytest
from datetime import datetime
from uuid import UUID

from heimdex_media_contracts.ingest import IngestSceneDocument, IngestScenesRequest


def _pipeline_scene_dict(**overrides) -> dict:
    base = {
        "scene_id": "gd_abc123_scene_000",
        "index": 0,
        "start_ms": 0,
        "end_ms": 5000,
        "keyframe_timestamp_ms": 2500,
        "transcript_raw": "",
        "speech_segment_count": 0,
        "keyword_tags": [],
        "product_tags": [],
        "product_entities": [],
        "ocr_text_raw": "",
        "ocr_char_count": 0,
        "source_type": "gdrive",
        "capture_time": None,
    }
    base.update(overrides)
    return base


class TestPipelineSceneDictAccepted:
    def test_minimal_scene(self):
        doc = IngestSceneDocument(**_pipeline_scene_dict())
        assert doc.scene_id == "gd_abc123_scene_000"
        assert doc.source_type == "gdrive"

    def test_with_capture_time_iso(self):
        dt = datetime(2026, 1, 15, 10, 30, 0)
        doc = IngestSceneDocument(**_pipeline_scene_dict(capture_time=dt.isoformat()))
        assert doc.capture_time == dt

    def test_with_capture_time_none(self):
        doc = IngestSceneDocument(**_pipeline_scene_dict(capture_time=None))
        assert doc.capture_time is None

    def test_with_transcript(self):
        doc = IngestSceneDocument(**_pipeline_scene_dict(
            transcript_raw="안녕하세요 오늘 특가 상품을 소개합니다",
            speech_segment_count=5,
        ))
        assert doc.transcript_raw == "안녕하세요 오늘 특가 상품을 소개합니다"
        assert doc.speech_segment_count == 5

    def test_with_ocr(self):
        doc = IngestSceneDocument(**_pipeline_scene_dict(
            ocr_text_raw="50% 할인",
            ocr_char_count=7,
        ))
        assert doc.ocr_text_raw == "50% 할인"
        assert doc.ocr_char_count == 7

    def test_with_tags(self):
        doc = IngestSceneDocument(**_pipeline_scene_dict(
            keyword_tags=["sale", "product"],
            product_tags=["cosmetics"],
            product_entities=["립스틱"],
        ))
        assert doc.keyword_tags == ["sale", "product"]
        assert doc.product_tags == ["cosmetics"]
        assert doc.product_entities == ["립스틱"]

    def test_keyframe_timestamp_preserved(self):
        doc = IngestSceneDocument(**_pipeline_scene_dict(keyframe_timestamp_ms=4200))
        assert doc.keyframe_timestamp_ms == 4200


class TestMultiSceneIngestRequest:
    def test_five_scene_request(self):
        scenes = [
            _pipeline_scene_dict(
                scene_id=f"gd_abc123_scene_{i:03d}",
                index=i,
                start_ms=i * 3000,
                end_ms=(i + 1) * 3000,
                keyframe_timestamp_ms=i * 3000 + 1500,
            )
            for i in range(5)
        ]

        req = IngestScenesRequest(
            video_id="gd_abc123",
            video_title="라이브방송_20260115.mp4",
            library_id=UUID("efe351ac-5031-45be-81a8-d437e7742ddb"),
            total_duration_ms=15000,
            scenes=scenes,
        )
        assert len(req.scenes) == 5
        assert req.scenes[0].scene_id == "gd_abc123_scene_000"
        assert req.scenes[4].scene_id == "gd_abc123_scene_004"

    def test_single_scene_backward_compat(self):
        req = IngestScenesRequest(
            video_id="gd_abc123",
            library_id=UUID("efe351ac-5031-45be-81a8-d437e7742ddb"),
            total_duration_ms=5000,
            scenes=[_pipeline_scene_dict()],
        )
        assert len(req.scenes) == 1

    def test_scene_indices_contiguous(self):
        scenes = [
            _pipeline_scene_dict(
                scene_id=f"gd_xyz789_scene_{i:03d}",
                index=i,
                start_ms=i * 2000,
                end_ms=(i + 1) * 2000,
            )
            for i in range(10)
        ]
        req = IngestScenesRequest(
            video_id="gd_xyz789",
            library_id=UUID("efe351ac-5031-45be-81a8-d437e7742ddb"),
            total_duration_ms=20000,
            scenes=scenes,
        )
        indices = [s.index for s in req.scenes]
        assert indices == list(range(10))
