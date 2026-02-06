import pytest
from unittest.mock import patch, MagicMock
import math

from app.modules.search.embedding import (
    EmbeddingService,
    get_embedding_service,
    get_query_embedding,
    get_passage_embedding,
    _generate_mock_embedding,
    E5_QUERY_PREFIX,
    E5_PASSAGE_PREFIX,
)


class TestMockEmbedding:
    def test_correct_dimension(self):
        embedding = _generate_mock_embedding("test", 1024)
        assert len(embedding) == 1024
    
    def test_normalized_to_unit_vector(self):
        embedding = _generate_mock_embedding("test text", 768)
        norm = math.sqrt(sum(x * x for x in embedding))
        assert norm == pytest.approx(1.0, rel=1e-6)
    
    def test_deterministic(self):
        emb1 = _generate_mock_embedding("hello world", 512)
        emb2 = _generate_mock_embedding("hello world", 512)
        assert emb1 == emb2
    
    def test_different_texts_different_embeddings(self):
        emb1 = _generate_mock_embedding("text one", 256)
        emb2 = _generate_mock_embedding("text two", 256)
        assert emb1 != emb2
    
    def test_korean_text(self):
        embedding = _generate_mock_embedding("한국어 테스트", 1024)
        assert len(embedding) == 1024
        norm = math.sqrt(sum(x * x for x in embedding))
        assert norm == pytest.approx(1.0, rel=1e-6)


class TestEmbeddingServiceMockMode:
    @patch("app.modules.search.embedding.get_settings")
    def test_mock_mode_returns_correct_dimension(self, mock_settings):
        settings = MagicMock()
        settings.embedding_use_mock = True
        settings.embedding_dimension = 1024
        mock_settings.return_value = settings
        
        EmbeddingService._instance = None
        EmbeddingService._model = None
        service = EmbeddingService()
        
        embedding = service.embed_query("test query")
        
        assert len(embedding) == 1024
    
    @patch("app.modules.search.embedding.get_settings")
    def test_query_and_passage_differ_in_mock_mode(self, mock_settings):
        settings = MagicMock()
        settings.embedding_use_mock = True
        settings.embedding_dimension = 1024
        mock_settings.return_value = settings
        
        EmbeddingService._instance = None
        EmbeddingService._model = None
        service = EmbeddingService()
        
        query_emb = service.embed_query("same text")
        passage_emb = service.embed_passage("same text")
        
        assert query_emb == passage_emb


class TestE5Prefixes:
    def test_query_prefix_defined(self):
        assert E5_QUERY_PREFIX == "query: "
    
    def test_passage_prefix_defined(self):
        assert E5_PASSAGE_PREFIX == "passage: "


class TestGetEmbeddingService:
    @patch("app.modules.search.embedding.get_settings")
    def test_singleton_pattern(self, mock_settings):
        settings = MagicMock()
        settings.embedding_use_mock = True
        settings.embedding_dimension = 1024
        mock_settings.return_value = settings
        
        EmbeddingService._instance = None
        EmbeddingService._model = None
        
        service1 = get_embedding_service()
        service2 = get_embedding_service()
        
        assert service1 is service2
