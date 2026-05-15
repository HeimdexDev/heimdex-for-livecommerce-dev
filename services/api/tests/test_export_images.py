from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse, Response

from app.modules.export.router import export_images
from app.modules.export.schemas import ExportImageItem, ExportImagesRequest
from app.modules.tenancy.context import OrgContext


def _make_request(items):
    return ExportImagesRequest(
        images=[ExportImageItem(**item) for item in items]
    )


def _make_org_ctx():
    return OrgContext(org_id=uuid4(), org_slug="testorg")


def _make_user():
    user = MagicMock()
    user.id = uuid4()
    return user


@pytest.fixture
def patched_export_deps():
    """Patch S3Client + get_settings inside the router module."""
    with patch("app.modules.export.router.S3Client") as s3_cls, \
         patch("app.modules.export.router.get_settings") as get_settings:
        settings = MagicMock()
        settings.drive_s3_bucket = "test-bucket"
        get_settings.return_value = settings

        s3_instance = MagicMock()
        s3_cls.return_value = s3_instance
        yield s3_instance


@pytest.mark.asyncio
async def test_single_image_returns_raw_jpeg(patched_export_deps):
    fake_bytes = b"\xff\xd8\xff\xe0FAKEJPG"
    patched_export_deps.get_object_bytes_async = AsyncMock(return_value=fake_bytes)

    req = _make_request([
        {"video_id": "gd_abc", "scene_id": "gd_abc_scene_005", "video_title": "Demo Video"},
    ])

    resp = await export_images(req, _make_org_ctx(), _make_user())

    assert isinstance(resp, Response)
    assert not isinstance(resp, FileResponse)
    assert resp.media_type == "image/jpeg"
    assert resp.body == fake_bytes
    disposition = resp.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "Demo Video_gd_abc_scene_005.jpg" in disposition
    assert ".zip" not in disposition


@pytest.mark.asyncio
async def test_single_image_dedupes_to_one_returns_jpeg(patched_export_deps):
    """Two identical scene_ids should still produce the single-file response."""
    patched_export_deps.get_object_bytes_async = AsyncMock(return_value=b"jpgbytes")

    req = _make_request([
        {"video_id": "gd_abc", "scene_id": "gd_abc_scene_001", "video_title": "X"},
        {"video_id": "gd_abc", "scene_id": "gd_abc_scene_001", "video_title": "X"},
    ])

    resp = await export_images(req, _make_org_ctx(), _make_user())

    assert resp.media_type == "image/jpeg"
    assert resp.body == b"jpgbytes"
    patched_export_deps.get_object_bytes_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_single_image_missing_keyframe_returns_404(patched_export_deps):
    patched_export_deps.get_object_bytes_async = AsyncMock(return_value=None)

    req = _make_request([
        {"video_id": "gd_abc", "scene_id": "gd_abc_scene_005", "video_title": "Demo"},
    ])

    with pytest.raises(HTTPException) as exc:
        await export_images(req, _make_org_ctx(), _make_user())

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_multi_image_returns_zip(patched_export_deps):
    patched_export_deps.get_object_bytes_async = AsyncMock(return_value=b"\xff\xd8jpg")

    req = _make_request([
        {"video_id": "gd_a", "scene_id": "gd_a_scene_001", "video_title": "A"},
        {"video_id": "gd_b", "scene_id": "gd_b_scene_002", "video_title": "B"},
    ])

    resp = await export_images(req, _make_org_ctx(), _make_user())

    assert isinstance(resp, FileResponse)
    assert resp.media_type == "application/zip"
    disposition = resp.headers["content-disposition"]
    assert "heimdex_images_" in disposition
    assert ".zip" in disposition
