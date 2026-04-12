"""Tests for the GPU reranker FastAPI service.

Uses a mock model to avoid GPU/model dependencies in CI.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create test client with mocked model."""
    import torch

    mock_tokenizer = MagicMock()
    mock_model = MagicMock()

    # Mock tokenizer returns dict-like object
    mock_inputs = {"input_ids": torch.zeros(2, 10, dtype=torch.long)}
    mock_tokenizer.return_value = MagicMock(
        **{"to.return_value": mock_inputs, **mock_inputs}
    )

    # Mock model returns logits
    mock_output = MagicMock()
    mock_output.logits = torch.tensor([[1.5], [-0.5]])
    mock_model.return_value = mock_output
    mock_model.parameters.return_value = [torch.zeros(10)]

    with patch("src.server.AutoTokenizer") as mock_tok_cls, \
         patch("src.server.AutoModelForSequenceClassification") as mock_model_cls, \
         patch("src.server.torch") as mock_torch:
        mock_tok_cls.from_pretrained.return_value = mock_tokenizer
        mock_model_cls.from_pretrained.return_value = mock_model
        mock_torch.cuda.is_available.return_value = False
        mock_torch.no_grad.return_value.__enter__ = MagicMock()
        mock_torch.no_grad.return_value.__exit__ = MagicMock()
        mock_torch.sigmoid.return_value.cpu.return_value.tolist.return_value = [0.82, 0.35]

        from src.server import app
        yield TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("ok", "loading")
        assert "model" in data
        assert "gpu_available" in data
        assert "device" in data


class TestRerankEndpoint:
    def test_rerank_returns_scores(self, client):
        response = client.post("/rerank", json={
            "query": "세럼 추천",
            "documents": ["세럼 제품 소개", "오늘의 날씨"],
        })
        assert response.status_code == 200
        data = response.json()
        assert "scores" in data
        assert len(data["scores"]) == 2
        assert "model" in data
        assert "latency_ms" in data

    def test_rerank_empty_documents(self, client):
        response = client.post("/rerank", json={
            "query": "test",
            "documents": [],
        })
        assert response.status_code == 200
        data = response.json()
        assert data["scores"] == []
        assert data["latency_ms"] == 0.0

    def test_rerank_single_document(self, client):
        response = client.post("/rerank", json={
            "query": "test",
            "documents": ["single doc"],
        })
        assert response.status_code == 200

    def test_rerank_missing_query(self, client):
        response = client.post("/rerank", json={
            "documents": ["doc1"],
        })
        assert response.status_code == 422

    def test_rerank_missing_documents(self, client):
        response = client.post("/rerank", json={
            "query": "test",
        })
        assert response.status_code == 422
