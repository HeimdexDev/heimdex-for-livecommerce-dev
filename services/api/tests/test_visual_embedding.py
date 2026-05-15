"""Tests for SigLIP2 visual embedding service (mock mode).

Tests run entirely in mock mode (EMBEDDING_USE_MOCK=true) to avoid
downloading the ~340MB SigLIP2 model in CI.  The mock generates
deterministic 768-dim L2-normalized vectors.
"""
import math

import pytest

from app.modules.search.visual_embedding import (
    VISUAL_EMBEDDING_DIMENSION,
    VisualEmbeddingService,
    _generate_mock_visual_embedding,
    get_visual_embedding_service,
)


class TestMockVisualEmbedding:
    """Test mock visual embedding generation."""

    def test_dimension(self) -> None:
        vec = _generate_mock_visual_embedding("test")
        assert len(vec) == VISUAL_EMBEDDING_DIMENSION

    def test_l2_normalized(self) -> None:
        vec = _generate_mock_visual_embedding("test query")
        norm = math.sqrt(sum(x * x for x in vec))
        assert abs(norm - 1.0) < 1e-6, f"Expected unit vector, got norm={norm}"

    def test_deterministic(self) -> None:
        a = _generate_mock_visual_embedding("같은 쿼리")
        b = _generate_mock_visual_embedding("같은 쿼리")
        assert a == b

    def test_different_inputs_differ(self) -> None:
        a = _generate_mock_visual_embedding("립스틱 추천")
        b = _generate_mock_visual_embedding("아이섀도우 추천")
        assert a != b

    def test_differs_from_e5_mock(self) -> None:
        """Visual mock must produce different vectors than E5 text mock."""
        from app.modules.search.embedding import _generate_mock_embedding

        text = "동일한 텍스트"
        visual_vec = _generate_mock_visual_embedding(text)
        e5_vec = _generate_mock_embedding(text, VISUAL_EMBEDDING_DIMENSION)

        # They should differ (visual mock uses "visual:" prefix in hash)
        assert visual_vec != e5_vec

    def test_empty_string(self) -> None:
        vec = _generate_mock_visual_embedding("")
        assert len(vec) == VISUAL_EMBEDDING_DIMENSION
        norm = math.sqrt(sum(x * x for x in vec))
        assert abs(norm - 1.0) < 1e-6

    def test_long_string(self) -> None:
        vec = _generate_mock_visual_embedding("한국어 " * 1000)
        assert len(vec) == VISUAL_EMBEDDING_DIMENSION


class TestVisualEmbeddingService:
    """Test the VisualEmbeddingService in mock mode."""

    @pytest.fixture(autouse=True)
    def _mock_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Force mock mode for all tests."""
        monkeypatch.setenv("EMBEDDING_USE_MOCK", "true")
        # Clear lru_cache on both settings and service singletons
        from app.config import get_settings
        get_settings.cache_clear()
        get_visual_embedding_service.cache_clear()

    def test_embed_query_returns_list(self) -> None:
        service = VisualEmbeddingService()
        vec = service.embed_query("화장품 리뷰")
        assert isinstance(vec, list)
        assert len(vec) == VISUAL_EMBEDDING_DIMENSION

    def test_embed_query_normalized(self) -> None:
        service = VisualEmbeddingService()
        vec = service.embed_query("매트 립스틱 색상")
        norm = math.sqrt(sum(x * x for x in vec))
        assert abs(norm - 1.0) < 1e-6

    def test_embed_query_cached(self) -> None:
        service = VisualEmbeddingService()
        a = service.embed_query("캐시 테스트 쿼리")
        b = service.embed_query("캐시 테스트 쿼리")
        assert a is b, "Second call should return same cached object"

    def test_cache_eviction(self) -> None:
        service = VisualEmbeddingService()
        # Fill cache beyond capacity
        for i in range(service._QUERY_CACHE_SIZE + 10):
            service.embed_query(f"query_{i}")
        # Oldest entries should be evicted
        assert len(service._query_cache) <= service._QUERY_CACHE_SIZE

    def test_mock_mode_returns_without_model(self) -> None:
        service = VisualEmbeddingService()
        # In mock mode, _model should remain None
        vec = service.embed_query("테스트")
        assert service._model is None
        assert len(vec) == VISUAL_EMBEDDING_DIMENSION

    def test_load_model_mock_returns_false(self) -> None:
        service = VisualEmbeddingService()
        result = service._load_model()
        assert result is False


class TestVisualEmbeddingDimension:
    """Test that dimension constant is consistent."""

    def test_dimension_is_768(self) -> None:
        assert VISUAL_EMBEDDING_DIMENSION == 768

    def test_config_matches(self) -> None:
        from app.config import get_settings
        get_settings.cache_clear()
        settings = get_settings()
        assert settings.visual_embedding_dimension == VISUAL_EMBEDDING_DIMENSION


class TestGetVisualEmbeddingService:
    """Test singleton access."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self) -> None:
        get_visual_embedding_service.cache_clear()

    def test_singleton(self) -> None:
        a = get_visual_embedding_service()
        b = get_visual_embedding_service()
        assert a is b

    def test_returns_correct_type(self) -> None:
        service = get_visual_embedding_service()
        assert isinstance(service, VisualEmbeddingService)
