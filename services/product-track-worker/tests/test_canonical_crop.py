"""Phase 3c-B tests for ``_fetch_canonical_crop``.

Replaces the Phase 3c-A NotImplementedError stub. Uses the new
``ApiClient.fetch_catalog_entry`` Pattern B endpoint to resolve
seed metadata, then S3-downloads the canonical crop bytes.

Tests pin:
  * Happy-path 3-tuple return (Image, BBoxXYWH, llm_label).
  * 404 from the api propagates to caller (catalog row missing).
  * Cross-tenant defence-in-depth: api response mismatch raises.
  * S3 ``None`` return raises FileNotFoundError with the s3_key.
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import httpx
import pytest
from PIL import Image

from heimdex_media_pipelines.product_track.sam2_pass import BBoxXYWH

from src.settings import WorkerSettings
from src.tasks.track import _fetch_canonical_crop, TrackJobMessage


def _settings() -> WorkerSettings:
    return WorkerSettings(
        product_v2_enabled=True,
        sqs_product_track_queue_url="https://sqs/q",
        drive_internal_api_key="t",
        drive_api_base_url="http://api:8000",
        drive_s3_bucket="test-bucket",
        worker_id="test-worker",
    )


def _decoded(*, org_id: UUID | None = None) -> TrackJobMessage:
    return TrackJobMessage(
        job_id=uuid4(),
        org_id=org_id or uuid4(),
        video_id=uuid4(),
        catalog_entry_id=uuid4(),
        requested_by_user_id=uuid4(),
        duration_preset_sec=60,
        tracker_version="v1.0",
        enumeration_prompt_version="v1.0",
        callback_base_url="",
    )


def _jpeg_bytes(*, w: int = 64, h: int = 64) -> bytes:
    img = Image.new("RGB", (w, h), (200, 100, 50))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def _payload(
    *,
    org_id: UUID,
    s3_key: str = "products/X/Y/abc.jpg",
    bbox: dict | None = None,
    label: str = "테스트 제품",
) -> dict:
    return {
        "catalog_entry_id": str(uuid4()),
        "org_id": str(org_id),
        "video_id": str(uuid4()),
        "canonical_crop_s3_key": s3_key,
        "canonical_bbox": bbox or {"x": 10, "y": 20, "w": 100, "h": 150},
        "llm_label": label,
    }


# ---------- happy path ----------


def test_returns_image_bbox_label_tuple():
    org_id = uuid4()
    decoded = _decoded(org_id=org_id)
    api = MagicMock()
    api.fetch_catalog_entry.return_value = _payload(org_id=org_id, label="핑크 세럼 병")
    s3 = MagicMock()
    s3.get_object_bytes.return_value = _jpeg_bytes()

    crop, bbox, label = _fetch_canonical_crop(
        api=api, s3=s3, decoded=decoded, settings=_settings(),
    )
    assert isinstance(crop, Image.Image)
    assert crop.mode == "RGB"
    assert bbox == BBoxXYWH(x=10, y=20, width=100, height=150)
    assert label == "핑크 세럼 병"
    # Worker passes (entry_id, org_id) — not (video_id) — so the
    # api can do Pattern B by entry directly.
    api.fetch_catalog_entry.assert_called_once_with(
        catalog_entry_id=decoded.catalog_entry_id,
        org_id=decoded.org_id,
    )
    s3.get_object_bytes.assert_called_once_with("products/X/Y/abc.jpg")


def test_passes_through_404_from_api():
    """A 404 from the catalog endpoint = entry missing or cross
    tenant. Worker bubbles to the dispatcher which routes to /fail
    with internal_error. We don't special-case to ``video_not_found``
    because the catalog row is downstream of the video, and absent
    catalog rows usually indicate row deletion or a corrupted enum
    pass — not a missing source video."""
    org_id = uuid4()
    decoded = _decoded(org_id=org_id)
    request = httpx.Request(
        "GET",
        f"http://api/internal/products/catalog/{decoded.catalog_entry_id}",
    )
    api = MagicMock()
    api.fetch_catalog_entry.side_effect = httpx.HTTPStatusError(
        "404 Not Found",
        request=request,
        response=httpx.Response(404, request=request),
    )
    s3 = MagicMock()

    with pytest.raises(httpx.HTTPStatusError) as exc:
        _fetch_canonical_crop(
            api=api, s3=s3, decoded=decoded, settings=_settings(),
        )
    assert exc.value.response.status_code == 404
    s3.get_object_bytes.assert_not_called()


def test_raises_when_response_org_does_not_match_job_org():
    """Defence-in-depth: api Pattern B should already 404 on cross
    tenant, but if the api side is misconfigured (e.g. Pattern B
    helper bypassed) and returns a different-org row, the worker
    refuses rather than seeding the pipeline with the wrong
    product."""
    job_org = uuid4()
    other_org = uuid4()
    decoded = _decoded(org_id=job_org)
    api = MagicMock()
    api.fetch_catalog_entry.return_value = _payload(org_id=other_org)
    s3 = MagicMock()

    with pytest.raises(RuntimeError, match="org"):
        _fetch_canonical_crop(
            api=api, s3=s3, decoded=decoded, settings=_settings(),
        )
    s3.get_object_bytes.assert_not_called()


def test_raises_file_not_found_when_s3_returns_none():
    """SDK's ``S3Client.get_object_bytes`` returns ``None`` on
    NoSuchKey or transient failures (it logs internally but
    returns None either way). Worker MUST surface this — silently
    decoding ``None`` would TypeError, but raising explicitly puts
    the s3_key in the error message so operators can locate the
    gap in product-enumerate-worker's upload."""
    org_id = uuid4()
    decoded = _decoded(org_id=org_id)
    api = MagicMock()
    api.fetch_catalog_entry.return_value = _payload(
        org_id=org_id, s3_key="products/missing/key.jpg",
    )
    s3 = MagicMock()
    s3.get_object_bytes.return_value = None

    with pytest.raises(FileNotFoundError) as exc:
        _fetch_canonical_crop(
            api=api, s3=s3, decoded=decoded, settings=_settings(),
        )
    assert "products/missing/key.jpg" in str(exc.value)
    assert str(decoded.catalog_entry_id) in str(exc.value)


def test_decodes_non_rgb_jpeg_to_rgb():
    """SigLIP2 requires 3-channel input; force RGB conversion at
    the worker boundary so a grayscale or RGBA upload doesn't
    produce silently-wrong embeddings downstream."""
    org_id = uuid4()
    decoded = _decoded(org_id=org_id)
    # Encode a grayscale JPEG (mode 'L') — JPEG codec writes it as
    # YCbCr but PIL re-opens as 'L'. Worker must convert to RGB.
    gray_img = Image.new("L", (32, 32), 128)
    buf = io.BytesIO()
    gray_img.save(buf, format="JPEG", quality=80)
    api = MagicMock()
    api.fetch_catalog_entry.return_value = _payload(org_id=org_id)
    s3 = MagicMock()
    s3.get_object_bytes.return_value = buf.getvalue()

    crop, _bbox, _label = _fetch_canonical_crop(
        api=api, s3=s3, decoded=decoded, settings=_settings(),
    )
    assert crop.mode == "RGB"
