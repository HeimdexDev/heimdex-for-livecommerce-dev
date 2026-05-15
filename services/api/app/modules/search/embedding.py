"""
Embedding service for semantic search.

Uses multilingual-e5-large for production embeddings with proper E5 prefixes.
Falls back to mock embeddings for testing when EMBEDDING_USE_MOCK=true.

## Model: intfloat/multilingual-e5-large

- **Dimension**: 1024 (E5-large output)
- **Languages**: 100+ languages including Korean, English, Chinese, Japanese

## E5 Prefixes (REQUIRED)

E5 models require specific prefixes for asymmetric retrieval:
- **Queries**: "query: " + query_text
- **Documents/Passages**: "passage: " + document_text

Without these prefixes, retrieval quality degrades significantly.

## Normalization and Similarity

- **L2 Normalization**: All embeddings are L2-normalized (unit vectors)
  - Applied via `normalize_embeddings=True` in sentence-transformers
  - Ensures all vectors have magnitude 1.0

- **Similarity Metric**: Cosine similarity (OpenSearch: `cosinesimil`)
  - For L2-normalized vectors: cosine(a, b) = dot_product(a, b)
  - This equivalence makes dot product faster while giving same results
  - OpenSearch uses HNSW with cosine similarity for efficient approximate kNN

## Why Cosine Similarity?

1. **E5 training objective**: Trained with InfoNCE loss which optimizes cosine similarity
2. **Scale invariance**: Cosine ignores magnitude, only considers direction
3. **Performance**: For normalized vectors, cosine = dot product (faster)
4. **Interpretability**: Scores range from -1 to 1 (0.7-1.0 typical for relevant matches)

## First Run Behavior

On first run, the model (~2.4GB) is downloaded from HuggingFace Hub.
This can take several minutes depending on network speed.
Subsequent runs use the cached model from `~/.cache/huggingface/hub/`.

Set `EMBEDDING_USE_MOCK=true` for development without the model download.
"""
import hashlib
import math
import struct
from functools import lru_cache
from typing import TYPE_CHECKING

from app.config import get_settings
from app.logging_config import get_logger

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = get_logger(__name__)

# E5 model requires specific prefixes for queries vs passages
E5_QUERY_PREFIX = "query: "
E5_PASSAGE_PREFIX = "passage: "


class EmbeddingService:
    """
    Embedding service for text-to-vector conversion.
    
    Uses multilingual-e5-large which supports 100+ languages including Korean.
    The model produces 1024-dimensional embeddings.
    
    Singleton access via get_embedding_service() which uses @lru_cache.
    """
    
    _QUERY_CACHE_SIZE = 128

    def __init__(self) -> None:
        self.settings = get_settings()
        self._model: "SentenceTransformer | None" = None
        self._query_cache: dict[str, list[float]] = {}
        self._query_cache_order: list[str] = []
        
    def _load_model(self) -> "SentenceTransformer | None":
        """Lazy load the model on first use."""
        if self._model is not None:
            return self._model
            
        if self.settings.embedding_use_mock:
            logger.info("embedding_mock_mode", reason="EMBEDDING_USE_MOCK=true")
            return None
        
        logger.info(
            "loading_embedding_model",
            model=self.settings.embedding_model,
            device=self.settings.embedding_device,
        )
        
        from sentence_transformers import SentenceTransformer
        
        self._model = SentenceTransformer(
            self.settings.embedding_model,
            device=self.settings.embedding_device,
        )
        
        logger.info(
            "embedding_model_loaded",
            model=self.settings.embedding_model,
            dimension=self._model.get_sentence_embedding_dimension(),
        )
        
        return self._model
    
    def embed_query(self, query: str) -> list[float]:
        """
        Generate embedding for a search query.
        
        E5 models require the "query: " prefix for queries to work correctly.
        Results are cached (LRU, 128 entries) since embedding inference is
        the dominant latency source (~800-1500ms on CPU).
        """
        cached = self._query_cache.get(query)
        if cached is not None:
            return cached

        if self.settings.embedding_use_mock:
            result = _generate_mock_embedding(query, self.settings.embedding_dimension)
        else:
            model = self._load_model()
            prefixed_query = f"{E5_QUERY_PREFIX}{query}"
            embedding = model.encode(
                prefixed_query,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            result = embedding.tolist()

        if len(self._query_cache_order) >= self._QUERY_CACHE_SIZE:
            evicted = self._query_cache_order.pop(0)
            self._query_cache.pop(evicted, None)
        self._query_cache[query] = result
        self._query_cache_order.append(query)

        return result
    
    def embed_passage(self, text: str) -> list[float]:
        """
        Generate embedding for a document/passage (e.g., transcript segment).
        
        E5 models require the "passage: " prefix for documents.
        """
        if self.settings.embedding_use_mock:
            return _generate_mock_embedding(text, self.settings.embedding_dimension)
        
        model = self._load_model()
        prefixed_text = f"{E5_PASSAGE_PREFIX}{text}"
        
        embedding = model.encode(
            prefixed_text,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        
        return embedding.tolist()
    
    def embed_passages_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """
        Batch embed multiple passages efficiently.
        
        Use this for bulk indexing to improve throughput.
        """
        if self.settings.embedding_use_mock:
            return [
                _generate_mock_embedding(text, self.settings.embedding_dimension)
                for text in texts
            ]
        
        model = self._load_model()
        prefixed_texts = [f"{E5_PASSAGE_PREFIX}{text}" for text in texts]
        
        embeddings = model.encode(
            prefixed_texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=batch_size,
        )
        
        return embeddings.tolist()


def _generate_mock_embedding(text: str, dimension: int) -> list[float]:
    """
    Generate a deterministic mock embedding from text for development/testing.
    Uses MD5 hash to create reproducible vectors.
    
    This is useful for:
    - Unit tests that don't need semantic similarity
    - Development without GPU
    - CI/CD pipelines
    """
    hash_bytes = hashlib.md5(text.encode("utf-8")).digest()
    
    embedding: list[float] = []
    for i in range(dimension):
        seed_bytes = hash_bytes + struct.pack("I", i)
        hash_val = hashlib.md5(seed_bytes).digest()
        int_val = int.from_bytes(hash_val[:4], byteorder="little", signed=False)
        normalized = (int_val / (2**32 - 1)) * 2.0 - 1.0
        embedding.append(normalized)
    
    # Normalize to unit vector
    norm = math.sqrt(sum(x * x for x in embedding))
    if norm > 0:
        embedding = [x / norm for x in embedding]
    
    return embedding


@lru_cache(maxsize=1)
def get_embedding_service() -> EmbeddingService:
    """Get the singleton embedding service instance."""
    return EmbeddingService()


async def get_query_embedding(query: str) -> list[float]:
    """
    Get embedding for a search query.
    
    This is the main entry point used by the search service.
    """
    service = get_embedding_service()
    return service.embed_query(query)


def get_passage_embedding(text: str) -> list[float]:
    """
    Get embedding for a document passage.
    
    Used during indexing to embed transcript segments.
    """
    service = get_embedding_service()
    return service.embed_passage(text)


def get_passage_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """
    Batch embed multiple passages.
    
    Used during bulk indexing for efficiency.
    """
    service = get_embedding_service()
    return service.embed_passages_batch(texts)


def generate_mock_embedding(text: str) -> list[float]:
    """
    Generate a mock embedding for seeding/testing.
    
    Uses the configured embedding dimension from settings.
    This is a public API for seed scripts and tests.
    """
    settings = get_settings()
    return _generate_mock_embedding(text, settings.embedding_dimension)
