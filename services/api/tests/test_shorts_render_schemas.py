"""Tests for shorts render Pydantic schemas."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from heimdex_media_contracts.composition import CompositionSpec, SceneClipSpec

from app.modules.shorts_render.schemas import (
    RenderJobCreate,
    RenderJobListResponse,
    RenderJobResponse,
    RenderStatusUpdate,
)


def _valid_composition() -> CompositionSpec:
    clip = SceneClipSpec(
        scene_id="s1",
        video_id="v1",
        start_ms=0,
        end_ms=10000,
        timeline_start_ms=0,
    )
    return CompositionSpec(scene_clips=[clip])


class TestRenderJobCreate:
    def test_valid_create(self):
        job = RenderJobCreate(video_id="v1", composition=_valid_composition())
        assert job.video_id == "v1"
        assert job.title is None

    def test_valid_create_with_title_none(self):
        job = RenderJobCreate(video_id="v1", title=None, composition=_valid_composition())
        assert job.title is None

    def test_composition_from_contracts(self):
        comp = _valid_composition()
        job = RenderJobCreate(video_id="v1", composition=comp)
        assert len(job.composition.scene_clips) == 1


class TestRenderJobResponse:
    def test_model_validate_from_orm(self):
        orm_obj = SimpleNamespace(
            id=uuid4(),
            video_id="v1",
            title="Test",
            status="queued",
            created_at=datetime.now(timezone.utc),
            completed_at=None,
            render_time_ms=None,
            output_duration_ms=None,
            output_size_bytes=None,
            error=None,
        )
        resp = RenderJobResponse.model_validate(orm_obj, from_attributes=True)
        assert resp.id == orm_obj.id
        assert resp.status == "queued"

    def test_download_url_defaults_none(self):
        orm_obj = SimpleNamespace(
            id=uuid4(),
            video_id="v1",
            title=None,
            status="completed",
            created_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            render_time_ms=1500,
            output_duration_ms=30000,
            output_size_bytes=1024000,
            error=None,
        )
        resp = RenderJobResponse.model_validate(orm_obj, from_attributes=True)
        assert resp.download_url is None


class TestRenderJobListResponse:
    def test_serializes(self):
        resp = RenderJobListResponse(items=[], total=0)
        data = resp.model_dump()
        assert data["items"] == []
        assert data["total"] == 0


class TestRenderStatusUpdate:
    def test_valid_status(self):
        update = RenderStatusUpdate(status="rendering")
        assert update.status == "rendering"

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            RenderStatusUpdate(status="invalid_status")
