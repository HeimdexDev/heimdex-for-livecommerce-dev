"""
Cross-encoder reranker for search result re-scoring.

Uses BAAI/bge-reranker-v2-m3 to rescore the top-k RRF candidates with
query-document cross-attention, then blends the reranker score with the
original RRF adjusted_score.

## Model: BAAI/bge-reranker-v2-m3

- **Type**: Cross-encoder (sequence classification)
- **Languages**: 100+ languages including Korean
- **Max length**: 512 tokens (query + document concatenated)
- **Memory**: ~560MB (FP32)

## Integration point

Called from scene_service._search_semantic() between compute_weighted_rrf()
and diversify_results(). Gated by `RERANKER_ENABLED` config flag.

## Efficiency

- Batch inference: all pairs scored in a single forward pass
- FP16 autocast on CPU for reduced memory bandwidth
- asyncio.to_thread wrapper to avoid blocking the event loop
- Lazy model loading (singleton pattern, same as EmbeddingService)
"""
from __future__ import annotations

import asyncio
import hashlib
import struct
from functools import lru_cache
from typing import TYPE_CHECKING

from app.config import get_settings
from app.logging_config import get_logger
from app.modules.search.fusion import RankedItem

if TYPE_CHECKING:
    import torch

logger = get_logger(__name__)


class RerankerService:
    """Cross-encoder reranker with lazy model loading and LRU caching."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._model: torch.nn.Module | None = None
        self._tokenizer = None

    def _load_model(self) -> None:
        if self._model is not None:
            return

        if self.settings.reranker_use_mock:
            logger.info("reranker_mock_mode", reason="RERANKER_USE_MOCK=true")
            return

        logger.info(
            "loading_reranker_model",
            model=self.settings.reranker_model,
        )

        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self._tokenizer = AutoTokenizer.from_pretrained(self.settings.reranker_model)
        self._model = AutoModelForSequenceClassification.from_pretrained(
            self.settings.reranker_model,
        )
        self._model.eval()

        param_count = sum(p.numel() for p in self._model.parameters())
        logger.info(
            "reranker_model_loaded",
            model=self.settings.reranker_model,
            parameters=f"{param_count / 1e6:.1f}M",
        )

    def score_pairs(self, query: str, documents: list[str]) -> list[float]:
        """Score query-document pairs in a single batch.

        Returns sigmoid-normalized scores in [0, 1] range.
        """
        if not documents:
            return []

        self._load_model()

        if self.settings.reranker_use_mock:
            return _mock_scores(query, documents)

        import torch

        pairs = [[query, doc] for doc in documents]
        inputs = self._tokenizer(
            pairs,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )

        with torch.no_grad(), torch.autocast("cpu"):
            logits = self._model(**inputs).logits.squeeze(-1)

        scores = torch.sigmoid(logits).tolist()
        # Handle single-item case where squeeze removes all dims
        if isinstance(scores, float):
            scores = [scores]
        return scores


@lru_cache(maxsize=1)
def get_reranker_service() -> RerankerService:
    return RerankerService()


def build_reranker_document(source: dict) -> str:
    """Build document text for reranker from OpenSearch _source fields.

    Combines scene_caption + transcript_norm + ocr_text_raw.
    Truncation is handled by the tokenizer, not here.
    """
    parts = []
    for field in ("scene_caption", "transcript_norm", "ocr_text_raw"):
        value = source.get(field)
        if value:
            parts.append(value)
    return " ".join(parts) if parts else ""


async def apply_reranking(
    query: str,
    ranked_items: list[RankedItem],
    remaining: list[RankedItem],
) -> list[RankedItem]:
    """Rerank top-k items and append the rest unchanged.

    1. Build document texts from RankedItem.source
    2. Score all pairs in a single batch (offloaded to thread)
    3. Blend reranker scores with normalized RRF scores
    4. Sort by blended score, append remaining items
    """
    if not ranked_items:
        return remaining

    settings = get_settings()
    service = get_reranker_service()
    documents = [build_reranker_document(item.source) for item in ranked_items]

    # Offload CPU-bound inference to thread pool
    reranker_scores = await asyncio.to_thread(service.score_pairs, query, documents)

    # Min-max normalize RRF adjusted_scores to [0, 1]
    rrf_scores = [item.adjusted_score for item in ranked_items]
    rrf_min = min(rrf_scores)
    rrf_max = max(rrf_scores)
    rrf_range = rrf_max - rrf_min if rrf_max > rrf_min else 1.0

    w = settings.reranker_blend_weight
    for item, reranker_score, rrf_score in zip(ranked_items, reranker_scores, rrf_scores):
        item.reranker_score = reranker_score
        normalized_rrf = (rrf_score - rrf_min) / rrf_range
        item.adjusted_score = w * reranker_score + (1 - w) * normalized_rrf

    ranked_items.sort(key=lambda x: x.adjusted_score, reverse=True)

    logger.info(
        "reranker_applied",
        query=query[:50],
        candidates=len(ranked_items),
        top_score=ranked_items[0].reranker_score if ranked_items else None,
        blend_weight=w,
    )

    return ranked_items + remaining


def _mock_scores(query: str, documents: list[str]) -> list[float]:
    """Deterministic mock scores for testing.

    Produces stable scores based on query+document hash so tests are
    reproducible. Scores decrease slightly with index to allow testing
    reorder behavior when documents are shuffled.
    """
    scores = []
    for i, doc in enumerate(documents):
        h = hashlib.md5(f"{query}:{doc}".encode()).digest()
        base = struct.unpack("H", h[:2])[0] / 65535.0
        # Scale to [0.3, 0.95] range with slight index decay
        score = 0.3 + 0.65 * base - 0.001 * i
        scores.append(max(0.0, min(1.0, score)))
    return scores
