"""
Closed-vocabulary VMD search client.

Calls the closed-vocab-search sidecar container to classify queries
against a ~160-term closed vocabulary. On match, returns a pre-computed
SigLIP prompt embedding for direct kNN search, bypassing the normal
semantic pipeline.

Fail-open: on any error, returns None and the caller falls through
to standard semantic search.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ClosedVocabResult:
    vocab: str
    axis: str
    tier: int
    embedding: list[float]
    prompted_text: str


class ClosedVocabClient:

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = None

    def _get_client(self):
        if self._client is None:
            import httpx

            timeout = self.settings.closed_vocab_timeout_ms / 1000
            self._client = httpx.AsyncClient(
                base_url=self.settings.closed_vocab_service_url,
                timeout=httpx.Timeout(timeout),
            )
        return self._client

    async def classify(self, query: str) -> ClosedVocabResult | None:
        if not self.settings.closed_vocab_enabled:
            return None
        if not self.settings.closed_vocab_service_url:
            return None

        try:
            client = self._get_client()
            response = await client.post("/classify", json={"query": query})
            response.raise_for_status()
            data = response.json()

            if data.get("vocab") is None:
                return None

            return ClosedVocabResult(
                vocab=data["vocab"],
                axis=data["axis"],
                tier=data["tier"],
                embedding=data["embedding"],
                prompted_text=data["prompted_text"],
            )
        except Exception as exc:
            logger.warning(
                "closed_vocab_service_error",
                error=str(exc),
                query=query[:50],
            )
            return None


@lru_cache(maxsize=1)
def get_closed_vocab_client() -> ClosedVocabClient:
    return ClosedVocabClient()
