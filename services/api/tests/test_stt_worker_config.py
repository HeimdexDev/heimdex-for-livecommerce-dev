from app.config import Settings
from app.modules.drive.repository import _compute_enrichment_state


class TestSttConfigDefaults:
    def test_stt_disabled_by_default(self):
        settings = Settings()
        assert settings.drive_stt_enabled is False

    def test_stt_default_model(self):
        settings = Settings()
        assert settings.drive_stt_model == "small"

    def test_stt_default_language(self):
        settings = Settings()
        assert settings.drive_stt_language == "ko"

    def test_stt_default_backend(self):
        settings = Settings()
        assert settings.drive_stt_backend == "faster-whisper"

    def test_stt_default_concurrency(self):
        settings = Settings()
        assert settings.drive_stt_concurrency == 1

    def test_stt_default_poll_interval(self):
        settings = Settings()
        assert settings.drive_stt_poll_interval_seconds == 30

    def test_stt_default_max_audio_seconds(self):
        settings = Settings()
        assert settings.drive_stt_max_audio_seconds == 3600


class TestEnrichmentStateWithStt:
    def test_stt_done_ocr_done(self):
        assert _compute_enrichment_state("done", "done") == "done"

    def test_stt_done_ocr_pending(self):
        assert _compute_enrichment_state("done", "pending") == "pending"

    def test_stt_done_ocr_failed(self):
        assert _compute_enrichment_state("done", "failed") == "failed_partial"

    def test_stt_failed_ocr_done(self):
        assert _compute_enrichment_state("failed", "done") == "failed_partial"

    def test_stt_running_ocr_done(self):
        assert _compute_enrichment_state("running", "done") == "running"

    def test_stt_done_ocr_none(self):
        assert _compute_enrichment_state("done", None) == "done"

    def test_stt_failed_ocr_none(self):
        assert _compute_enrichment_state("failed", None) == "failed"
