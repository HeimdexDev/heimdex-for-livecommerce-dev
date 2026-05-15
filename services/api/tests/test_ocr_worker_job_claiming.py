from app.config import Settings
from app.modules.drive.repository import _compute_enrichment_state


class TestComputeEnrichmentState:
    def test_both_done(self):
        assert _compute_enrichment_state("done", "done") == "done"

    def test_both_failed(self):
        assert _compute_enrichment_state("failed", "failed") == "failed"

    def test_ocr_done_stt_failed(self):
        assert _compute_enrichment_state("failed", "done") == "failed_partial"

    def test_ocr_failed_stt_done(self):
        assert _compute_enrichment_state("done", "failed") == "failed_partial"

    def test_ocr_done_stt_pending(self):
        assert _compute_enrichment_state("pending", "done") == "pending"

    def test_ocr_done_stt_running(self):
        assert _compute_enrichment_state("running", "done") == "running"

    def test_ocr_done_stt_none(self):
        assert _compute_enrichment_state(None, "done") == "done"

    def test_ocr_failed_stt_none(self):
        assert _compute_enrichment_state(None, "failed") == "failed"

    def test_ocr_pending_stt_none(self):
        assert _compute_enrichment_state(None, "pending") == "pending"

    def test_both_none(self):
        assert _compute_enrichment_state(None, None) == "pending"

    def test_both_running(self):
        assert _compute_enrichment_state("running", "running") == "running"

    def test_ocr_pending_stt_failed(self):
        assert _compute_enrichment_state("failed", "pending") == "pending"


class TestOcrConfigDefaults:
    def test_ocr_disabled_by_default(self):
        settings = Settings()
        assert settings.drive_ocr_enabled is False

    def test_ocr_default_concurrency(self):
        settings = Settings()
        assert settings.drive_ocr_concurrency == 1

    def test_ocr_default_max_frames(self):
        settings = Settings()
        assert settings.drive_ocr_max_frames_per_scene == 10
        assert settings.drive_ocr_max_frames_per_video == 300
