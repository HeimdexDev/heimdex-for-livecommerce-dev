"""
Protocol interfaces for dependency injection.

These protocols define the contracts that implementations must satisfy,
enabling proper DI patterns and testability.
"""
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SearchIndexProtocol(Protocol):
    """Interface for search index operations (OpenSearch implementation)."""
    
    async def search_lexical(
        self,
        query: str,
        org_id: str,
        filters: dict[str, Any],
        size: int = 200,
    ) -> list[dict[str, Any]]:
        """Execute lexical (BM25) search."""
        ...
    
    async def search_vector(
        self,
        embedding: list[float],
        org_id: str,
        filters: dict[str, Any],
        size: int = 200,
    ) -> list[dict[str, Any]]:
        """Execute vector (kNN) search."""
        ...
    
    async def get_facets(
        self,
        org_id: str,
        filters: dict[str, Any],
    ) -> dict[str, list[dict[str, Any]]]:
        """Get aggregation facets."""
        ...
    
    async def close(self) -> None:
        """Close the client connection."""
        ...


@runtime_checkable
class EmbedderProtocol(Protocol):
    """Interface for text embedding (E5 implementation, Mock implementation)."""
    
    def embed_query(self, query: str) -> list[float]:
        """Generate embedding for a search query."""
        ...
    
    def embed_passage(self, text: str) -> list[float]:
        """Generate embedding for a document passage."""
        ...
    
    def embed_passages_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """Batch embed multiple passages."""
        ...
