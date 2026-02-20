"""Tests for caption enrichment: config, _compute_enrichment_state with caption_status, and search schema."""
from uuid import UUID

from app.config import Settings
from app.modules.drive.repository import _compute_enrichment_state
from app.modules.search.schemas import DebugInfo, SceneResult


class TestCaptionConfig:
    def test_caption_defaults(self):
        settings = Settings()
        assert settings.scene_caption_enabled is False
        assert settings.drive_caption_poll_interval_seconds == 30
        assert settings.drive_caption_concurrency == 1
        assert settings.drive_caption_model == "OpenGVLab/InternVL2-1B"

    def test_caption_can_be_enabled(self):
        settings = Settings(scene_caption_enabled=True)
        assert settings.scene_caption_enabled is True


class TestComputeEnrichmentStateWithCaption:
    def test_all_done_including_caption(self):
        assert _compute_enrichment_state("done", "done", "done") == "done"

    def test_caption_pending_others_done(self):
        assert _compute_enrichment_state("done", "done", "pending") == "pending"

    def test_caption_running(self):
        assert _compute_enrichment_state("done", "done", "running") == "running"

    def test_caption_failed_others_done(self):
        assert _compute_enrichment_state("done", "done", "failed") == "failed_partial"

    def test_all_failed_including_caption(self):
        assert _compute_enrichment_state("failed", "failed", "failed") == "failed"

    def test_caption_none_backward_compatible(self):
        assert _compute_enrichment_state("done", "done", None) == "done"
        assert _compute_enrichment_state("done", "done") == "done"

    def test_no_statuses(self):
        assert _compute_enrichment_state(None, None, None) == "pending"


class TestSceneResultCaptionField:
    def test_scene_result_caption_default_empty(self):
        result = SceneResult(
            scene_id="s1",
            video_id="v1",
            library_id=UUID("00000000-0000-0000-0000-000000000001"),
            library_name="test",
            start_ms=0,
            end_ms=1000,
            snippet="hello",
            thumbnail_url=None,
            source_type="gdrive",
            debug=DebugInfo(fused_score=1.0, adjusted_score=1.0),
        )
        assert result.scene_caption == ""

    def test_scene_result_caption_roundtrip(self):
        result = SceneResult(
            scene_id="s1",
            video_id="v1",
            library_id=UUID("00000000-0000-0000-0000-000000000001"),
            library_name="test",
            start_ms=0,
            end_ms=1000,
            snippet="hello",
            scene_caption="여성 호스트가 스킨케어 제품을 소개하고 있다",
            thumbnail_url=None,
            source_type="gdrive",
            debug=DebugInfo(fused_score=1.0, adjusted_score=1.0),
        )
        assert result.scene_caption == "여성 호스트가 스킨케어 제품을 소개하고 있다"
