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


async def startup_closed_vocab_check(settings) -> None:
    """Probe the closed-vocab-search sidecar's /health on boot.

    Runs only when ``CLOSED_VOCAB_ENABLED=true``. Logs ``ERROR`` if the
    service is unreachable so operators see the issue at startup rather
    than discovering it post-deploy via degraded search and a per-query
    ``closed_vocab_service_error`` WARNING that's easy to miss.

    Does NOT raise. ``ClosedVocabClient.classify`` is intentionally
    fail-open — if the sidecar is down, semantic search continues to
    work via the pure pipeline. The loud startup signal exists so
    that "search degraded" incidents have a single clear breadcrumb.

    Lives in this module (not ``app/main.py``) so unit tests importing
    it don't pull in ``app/main.py``'s eager ``setup_logging()`` side
    effect — that reconfigures structlog and breaks ``capsys``-based
    log assertions in sibling test files. (Bisected during PR 171 CI.)
    """
    if not settings.closed_vocab_enabled:
        return
    base_url = settings.closed_vocab_service_url
    if not base_url:
        logger.error(
            "closed_vocab_startup_misconfigured",
            message="CLOSED_VOCAB_ENABLED=true but CLOSED_VOCAB_SERVICE_URL is empty. "
                    "Every classify() call will short-circuit to None and search "
                    "will silently fall through to the pure pipeline.",
        )
        return
    try:
        import httpx

        timeout = httpx.Timeout(settings.closed_vocab_timeout_ms / 1000)
        async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
            response = await client.get("/health")
            response.raise_for_status()
            payload = response.json() if response.content else {}
            logger.info(
                "closed_vocab_startup_ok",
                base_url=base_url,
                vocab_size=payload.get("vocab_size"),
                status=payload.get("status"),
            )
    except Exception as exc:
        logger.error(
            "closed_vocab_startup_unreachable",
            base_url=base_url,
            error=str(exc),
            message="Sidecar is unreachable but CLOSED_VOCAB_ENABLED=true. "
                    "Search will silently fall through to the pure pipeline "
                    "and per-query WARNING logs will accumulate.",
        )
