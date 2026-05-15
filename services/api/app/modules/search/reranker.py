"""
Cross-encoder reranker client for search result re-scoring.

Calls a GPU reranker service via HTTP to rescore top-k RRF candidates,
then blends the reranker score with the original RRF adjusted_score.

## Architecture

The reranker model runs on a dedicated Aircloud GPU endpoint as a
FastAPI service. This module is an HTTP client — no torch, no model
loading, no GPU dependency in the API process.

## Fail-open

If the GPU service is unavailable (timeout, connection error), reranking
is skipped and results are returned in original RRF order. Search never
fails due to reranker issues.

## Integration point

Called from scene_service._search_semantic() between compute_weighted_rrf()
and diversify_results(). Gated by `RERANKER_ENABLED` config flag.
"""
from __future__ import annotations

import hashlib
import struct
from functools import lru_cache

from app.config import get_settings
from app.logging_config import get_logger
from app.modules.search.fusion import RankedItem

logger = get_logger(__name__)


class RerankerClient:
    """HTTP client for the GPU reranker service."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = None

    def _get_client(self):
        if self._client is None:
            import httpx

            timeout = self.settings.reranker_timeout_ms / 1000
            headers = {}
            if self.settings.aircloud_api_key:
                headers["x-api-key"] = self.settings.aircloud_api_key
            self._client = httpx.AsyncClient(
                base_url=self.settings.reranker_service_url,
                timeout=httpx.Timeout(timeout),
                headers=headers,
            )
        return self._client

    async def score_pairs(self, query: str, documents: list[str]) -> list[float]:
        """Score query-document pairs via the GPU reranker service.

        Returns sigmoid-normalized scores in [0, 1] range.
        Raises on HTTP errors (caller handles fail-open).
        """
        if not documents:
            return []

        if self.settings.reranker_use_mock:
            return _mock_scores(query, documents)

        client = self._get_client()
        response = await client.post(
            "/rerank",
            json={"query": query, "documents": documents},
        )
        response.raise_for_status()
        return response.json()["scores"]


@lru_cache(maxsize=1)
def get_reranker_client() -> RerankerClient:
    return RerankerClient()


def build_reranker_document(source: dict) -> str:
    """Build document text for reranker from OpenSearch _source fields.

    Combines scene_caption + transcript_norm + ocr_text_raw.
    Truncation is handled by the GPU service's tokenizer, not here.
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
    2. Score all pairs via GPU service (or mock)
    3. Blend reranker scores with normalized RRF scores
    4. Sort by blended score, append remaining items

    Fail-open: on any error, returns items in original RRF order.
    """
    if not ranked_items:
        return remaining

    settings = get_settings()
    client = get_reranker_client()
    documents = [build_reranker_document(item.source) for item in ranked_items]

    try:
        reranker_scores = await client.score_pairs(query, documents)
    except Exception as exc:
        logger.warning(
            "reranker_service_error",
            error=str(exc),
            query=query[:50],
            candidates=len(ranked_items),
        )
        return ranked_items + remaining

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
        score = 0.3 + 0.65 * base - 0.001 * i
        scores.append(max(0.0, min(1.0, score)))
    return scores
