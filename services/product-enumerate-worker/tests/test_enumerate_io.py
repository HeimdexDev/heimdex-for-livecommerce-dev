"""Phase 2.5b — tests for the worker-side I/O helpers
``_fetch_keyframes`` and ``_upload_crops_and_build_payload``.

The helpers are the only places where the worker hits the network /
S3, so they're the highest-risk surface in the worker. Tests stub the
HTTP client + S3Client so the suite stays unit-level.
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from PIL import Image

from heimdex_media_pipelines.product_enum.pipeline import CanonicalProduct

from src.settings import WorkerSettings
from src.tasks.enumerate import (
    _fetch_keyframes,
    _upload_crops_and_build_payload,
)


def _settings() -> WorkerSettings:
    return WorkerSettings(
        product_v2_enabled=True,
        sqs_product_enumerate_queue_url="https://sqs/q",
        drive_internal_api_key="test-token",
        drive_api_base_url="http://api:8000",
        drive_s3_bucket="test-bucket",
        openai_api_key="sk-test",
    )


def _make_jpeg_bytes(w: int = 100, h: int = 100, fill: int = 128) -> bytes:
    img = Image.new("RGB", (w, h), (fill, fill, fill))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def _make_canonical_product(
    *,
    rejected: str | None = None,
) -> CanonicalProduct:
    return CanonicalProduct(
        canonical_scene_id="gd_test_scene_007",
        canonical_frame_idx=14000,
        canonical_bbox_xywh=(100, 50, 200, 300),
        canonical_crop=Image.new("RGB", (200, 300), (200, 100, 50)),
        llm_label="핑크 세럼 병",
        siglip2_embedding=[0.1] * 768,
        enumeration_confidence=0.87,
        prominence_score=0.42,
        cluster_size=3,
        rejected_reason=rejected,
    )


# =========================================================================
# _fetch_keyframes
# =========================================================================

class TestFetchKeyframes:
    def test_happy_path_downloads_and_decodes_each_keyframe(self):
        """Standard run: 3 scenes, all keyframes present in S3,
        all decode cleanly."""
        scene_response = {
            "video_id": "gd_abc",
            "drive_file_id": str(uuid4()),
            "total_duration_ms": 60000,
            "scenes": [
                {
                    "scene_id": "gd_abc_scene_001",
                    "start_ms": 0, "end_ms": 20000,
                    "keyframe_timestamp_ms": 10000,
                    "keyframe_s3_key": "org/drive/keyframes/gd_abc/gd_abc_scene_001.jpg",
                },
                {
                    "scene_id": "gd_abc_scene_002",
                    "start_ms": 20000, "end_ms": 40000,
                    "keyframe_timestamp_ms": 30000,
                    "keyframe_s3_key": "org/drive/keyframes/gd_abc/gd_abc_scene_002.jpg",
                },
                {
                    "scene_id": "gd_abc_scene_003",
                    "start_ms": 40000, "end_ms": 60000,
                    "keyframe_timestamp_ms": None,
                    "keyframe_s3_key": "org/drive/keyframes/gd_abc/gd_abc_scene_003.jpg",
                },
            ],
        }
        s3 = MagicMock()
        s3.get_object_bytes.return_value = _make_jpeg_bytes()

        with patch("src.tasks.enumerate.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_resp = MagicMock(status_code=200)
            mock_resp.json.return_value = scene_response
            mock_resp.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_resp

            result = _fetch_keyframes(
                settings=_settings(),
                org_id=uuid4(),
                video_id=uuid4(),
                max_keyframes=60,
                api_base_url="http://api:8000",
                s3_client=s3,
            )

        assert len(result) == 3
        assert [kf.scene_id for kf in result] == [
            "gd_abc_scene_001", "gd_abc_scene_002", "gd_abc_scene_003",
        ]
        # frame_idx carries keyframe_timestamp_ms; null becomes 0.
        assert result[0].frame_idx == 10000
        assert result[1].frame_idx == 30000
        assert result[2].frame_idx == 0
        # All three keyframes decoded into PIL images.
        for kf in result:
            assert kf.image.size == (100, 100)

    def test_404_returns_empty_list(self):
        """API 404 (video not registered) → empty list. Caller
        treats this as ``video_not_found``."""
        s3 = MagicMock()
        with patch("src.tasks.enumerate.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.get.return_value = MagicMock(status_code=404)
            result = _fetch_keyframes(
                settings=_settings(),
                org_id=uuid4(), video_id=uuid4(),
                max_keyframes=60,
                api_base_url="http://api:8000", s3_client=s3,
            )
        assert result == []
        s3.get_object_bytes.assert_not_called()

    def test_http_error_returns_empty_list(self):
        """Any non-404 HTTP error → empty list (defensive). Caller
        sees ``video_not_found`` rather than the worker crashing."""
        import httpx
        s3 = MagicMock()
        with patch("src.tasks.enumerate.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.get.side_effect = httpx.ConnectError("api down")
            result = _fetch_keyframes(
                settings=_settings(),
                org_id=uuid4(), video_id=uuid4(),
                max_keyframes=60,
                api_base_url="http://api:8000", s3_client=s3,
            )
        assert result == []

    def test_missing_s3_object_skipped_others_kept(self):
        """One bad S3 object out of N must NOT abort the whole job;
        the pipeline tolerates a sparse keyframe set."""
        scene_response = {
            "scenes": [
                {
                    "scene_id": "s1", "start_ms": 0, "end_ms": 100,
                    "keyframe_timestamp_ms": 50,
                    "keyframe_s3_key": "key1.jpg",
                },
                {
                    "scene_id": "s2", "start_ms": 100, "end_ms": 200,
                    "keyframe_timestamp_ms": 150,
                    "keyframe_s3_key": "key2.jpg",  # this one will be missing
                },
                {
                    "scene_id": "s3", "start_ms": 200, "end_ms": 300,
                    "keyframe_timestamp_ms": 250,
                    "keyframe_s3_key": "key3.jpg",
                },
            ],
        }
        good = _make_jpeg_bytes()
        s3 = MagicMock()
        # Returns None for key2 (NoSuchKey), bytes for the others.
        s3.get_object_bytes.side_effect = lambda k: None if k == "key2.jpg" else good

        with patch("src.tasks.enumerate.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_resp = MagicMock(status_code=200)
            mock_resp.json.return_value = scene_response
            mock_resp.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_resp

            result = _fetch_keyframes(
                settings=_settings(),
                org_id=uuid4(), video_id=uuid4(),
                max_keyframes=60,
                api_base_url="http://api:8000", s3_client=s3,
            )
        assert [kf.scene_id for kf in result] == ["s1", "s3"]

    def test_subsamples_when_scene_count_exceeds_max(self):
        """30 scenes with ``max_keyframes=5`` — only 5 S3 fetches
        should happen (cost-bounded)."""
        scenes = [
            {
                "scene_id": f"s{i}", "start_ms": i * 1000, "end_ms": (i + 1) * 1000,
                "keyframe_timestamp_ms": i * 1000 + 500,
                "keyframe_s3_key": f"k{i}.jpg",
            }
            for i in range(30)
        ]
        s3 = MagicMock()
        s3.get_object_bytes.return_value = _make_jpeg_bytes()

        with patch("src.tasks.enumerate.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_resp = MagicMock(status_code=200)
            mock_resp.json.return_value = {"scenes": scenes}
            mock_resp.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_resp

            result = _fetch_keyframes(
                settings=_settings(),
                org_id=uuid4(), video_id=uuid4(),
                max_keyframes=5,
                api_base_url="http://api:8000", s3_client=s3,
            )
        assert len(result) == 5
        # Subsampling is even-stride; first scene + last scene must
        # bracket the result (gives the LLM coverage of intro + outro).
        assert result[0].scene_id == "s0"

    def test_empty_scene_list_returns_empty(self):
        s3 = MagicMock()
        with patch("src.tasks.enumerate.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_resp = MagicMock(status_code=200)
            mock_resp.json.return_value = {"scenes": []}
            mock_resp.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_resp

            result = _fetch_keyframes(
                settings=_settings(),
                org_id=uuid4(), video_id=uuid4(),
                max_keyframes=60,
                api_base_url="http://api:8000", s3_client=s3,
            )
        assert result == []
        s3.get_object_bytes.assert_not_called()

    def test_decode_failure_skipped(self):
        """If the keyframe bytes don't decode as an image (corrupt /
        wrong content-type / etc.), skip it without aborting the
        rest of the run."""
        scene_response = {
            "scenes": [
                {
                    "scene_id": "s_good", "start_ms": 0, "end_ms": 100,
                    "keyframe_timestamp_ms": 50, "keyframe_s3_key": "good.jpg",
                },
                {
                    "scene_id": "s_bad", "start_ms": 100, "end_ms": 200,
                    "keyframe_timestamp_ms": 150, "keyframe_s3_key": "bad.bin",
                },
            ],
        }
        s3 = MagicMock()
        s3.get_object_bytes.side_effect = lambda k: (
            _make_jpeg_bytes() if k == "good.jpg" else b"not an image"
        )

        with patch("src.tasks.enumerate.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_resp = MagicMock(status_code=200)
            mock_resp.json.return_value = scene_response
            mock_resp.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_resp

            result = _fetch_keyframes(
                settings=_settings(),
                org_id=uuid4(), video_id=uuid4(),
                max_keyframes=60,
                api_base_url="http://api:8000", s3_client=s3,
            )
        assert [kf.scene_id for kf in result] == ["s_good"]


# =========================================================================
# _upload_crops_and_build_payload
# =========================================================================

class TestUploadCrops:
    def test_payload_shape_matches_api_validator(self):
        """Built payload must satisfy
        ``app.modules.shorts_auto_product.internal_router._CatalogEntryPayload``
        — drift here = 400 on the complete callback."""
        org_id = uuid4()
        video_id = uuid4()
        product = _make_canonical_product()
        s3 = MagicMock()
        s3.bucket = "test-bucket"
        s3._client = MagicMock()

        payloads = _upload_crops_and_build_payload(
            settings=_settings(),
            org_id=org_id,
            video_id=video_id,
            products=[product],
            enumeration_version="v1.0",
            enumeration_prompt_version="v1.0",
            s3_client=s3,
        )
        assert len(payloads) == 1
        p = payloads[0]
        # Every required field present + correct type.
        required = {
            "canonical_crop_s3_key", "canonical_video_id",
            "canonical_frame_idx", "canonical_bbox", "llm_label",
            "siglip2_embedding", "enumeration_confidence",
            "prominence_score", "enumeration_version",
            "enumeration_prompt_version",
        }
        assert required.issubset(p.keys())
        assert p["canonical_video_id"] == str(video_id)
        assert p["canonical_frame_idx"] == 14000
        assert p["canonical_bbox"] == {"x": 100, "y": 50, "w": 200, "h": 300}
        assert p["llm_label"] == "핑크 세럼 병"
        assert len(p["siglip2_embedding"]) == 768
        assert p["enumeration_version"] == "v1.0"
        # S3 key uses the documented path layout.
        assert p["canonical_crop_s3_key"].startswith(
            f"products/{org_id}/{video_id}/"
        )
        assert p["canonical_crop_s3_key"].endswith(".jpg")

    def test_uploads_each_product_to_s3(self):
        product = _make_canonical_product()
        s3 = MagicMock()
        s3.bucket = "test-bucket"
        s3._client = MagicMock()

        _upload_crops_and_build_payload(
            settings=_settings(),
            org_id=uuid4(), video_id=uuid4(),
            products=[product, product, product],
            enumeration_version="v1.0",
            enumeration_prompt_version="v1.0",
            s3_client=s3,
        )
        # Three products → three put_object calls.
        assert s3._client.put_object.call_count == 3
        # Each call uses image/jpeg content-type.
        for call in s3._client.put_object.call_args_list:
            assert call.kwargs["ContentType"] == "image/jpeg"
            assert call.kwargs["Bucket"] == "test-bucket"
            assert call.kwargs["Key"].endswith(".jpg")

    def test_upload_failure_drops_entry_from_payload(self):
        """A single S3 upload failure must NOT include that product
        in the returned payload (the API would persist a row pointing
        at a missing object — worse than dropping it silently)."""
        s3 = MagicMock()
        s3.bucket = "test-bucket"
        s3._client = MagicMock()

        # First product upload fails, second succeeds.
        side_effects = [Exception("S3 unavailable"), None]
        s3._client.put_object.side_effect = side_effects

        result = _upload_crops_and_build_payload(
            settings=_settings(),
            org_id=uuid4(), video_id=uuid4(),
            products=[_make_canonical_product(), _make_canonical_product()],
            enumeration_version="v1.0",
            enumeration_prompt_version="v1.0",
            s3_client=s3,
        )
        assert len(result) == 1

    def test_rejected_products_still_uploaded(self):
        """Rejected entries are still posted to the API (the API
        persists the rejected_reason for threshold tuning), so they
        also need their canonical_crop uploaded for inspection."""
        rejected = _make_canonical_product(rejected="single_keyframe")
        accepted = _make_canonical_product()
        s3 = MagicMock()
        s3.bucket = "test-bucket"
        s3._client = MagicMock()

        result = _upload_crops_and_build_payload(
            settings=_settings(),
            org_id=uuid4(), video_id=uuid4(),
            products=[rejected, accepted],
            enumeration_version="v1.0",
            enumeration_prompt_version="v1.0",
            s3_client=s3,
        )
        assert len(result) == 2
        assert s3._client.put_object.call_count == 2

    def test_empty_products_returns_empty_payload(self):
        s3 = MagicMock()
        s3.bucket = "test-bucket"
        s3._client = MagicMock()
        result = _upload_crops_and_build_payload(
            settings=_settings(),
            org_id=uuid4(), video_id=uuid4(),
            products=[],
            enumeration_version="v1.0",
            enumeration_prompt_version="v1.0",
            s3_client=s3,
        )
        assert result == []
        s3._client.put_object.assert_not_called()
