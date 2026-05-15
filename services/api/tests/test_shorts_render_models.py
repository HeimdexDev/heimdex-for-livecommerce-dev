"""Tests for ShortsRenderJob SQLAlchemy model (no live database required)."""

from uuid import uuid4

from app.modules.shorts_render.models import ShortsRenderJob


class TestShortsRenderJobModel:
    def test_tablename(self):
        assert ShortsRenderJob.__tablename__ == "shorts_render_jobs"

    def test_instance_creation(self):
        job = ShortsRenderJob(
            org_id=uuid4(),
            user_id=uuid4(),
            video_id="v1",
            title="Test Render",
            input_spec={"output": {}, "scene_clips": []},
        )
        assert job.video_id == "v1"
        assert job.title == "Test Render"

    def test_status_server_default(self):
        col = ShortsRenderJob.__table__.c.status
        assert col.server_default is not None
        assert col.server_default.arg == "queued"

    def test_has_timestamp_mixin_fields(self):
        columns = {c.name for c in ShortsRenderJob.__table__.columns}
        assert "created_at" in columns
        assert "updated_at" in columns

    def test_has_uuid_mixin_id(self):
        columns = {c.name for c in ShortsRenderJob.__table__.columns}
        assert "id" in columns
        pk_cols = [c.name for c in ShortsRenderJob.__table__.primary_key.columns]
        assert "id" in pk_cols
