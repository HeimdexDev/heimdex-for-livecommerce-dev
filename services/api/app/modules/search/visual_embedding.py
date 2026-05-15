"""
SigLIP2 visual embedding service for cross-modal search.

Uses google/siglip2-base-patch16-256 text encoder to produce 768-dim embeddings
that live in the same vector space as visual embeddings produced by the
SigLIP2 vision encoder running on Aircloud+ GPU workers.

## Model: google/siglip2-base-patch16-256

- **Dimension**: 768 (SigLIP2 base output)
- **Languages**: Multilingual (SigLIP2 trained on WebLI with multilingual alt-text)
- **Architecture**: Text tower of a vision-language contrastive model

## Key Implementation Details

1. **Padding**: MUST use `padding="max_length"` — the model was trained this way.
   Without it, embeddings degrade significantly.
2. **Max Length**: 64 tokens (matches `max_position_embeddings` in model config).
3. **Padding Side**: Left (hardcoded in `Siglip2Tokenizer`; we don't override it).
4. **Normalization**: L2-normalize the output ourselves — SigLIP2 does NOT
   auto-normalize unlike sentence-transformers models.
5. **Pooling**: `pooler_output` = EOS token hidden → linear projection → [B, 768].
6. **Dtype**: BF16 on CPU (better numerical stability than FP16 on CPU).
7. **Memory**: ~172MB in BF16 (~86M params × 2 bytes).

## Relationship to Vision Encoder

The text encoder produces embeddings in the SAME space as the vision encoder.
This enables cross-modal retrieval: user types Korean text query → text encoder →
768-dim vector → kNN against visual embeddings produced from keyframes.

## First Run

Downloads ~340MB from HuggingFace (tokenizer + text model weights).
Cached at `~/.cache/huggingface/hub/` or `$HF_HOME`.

Set `EMBEDDING_USE_MOCK=true` to skip model download in dev/CI.
"""
import hashlib
import math
import struct
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from app.config import get_settings
from app.logging_config import get_logger

if TYPE_CHECKING:
    import torch
    from transformers import SiglipTextModel
logger = get_logger(__name__)

VISUAL_EMBEDDING_DIMENSION = 768
_SIGLIP2_MODEL_NAME = "google/siglip2-base-patch16-256"
_SIGLIP2_MAX_LENGTH = 64


class VisualEmbeddingService:
    """SigLIP2 text encoder for cross-modal visual search.

    Produces 768-dim embeddings in the same vector space as SigLIP2 vision
    embeddings.  Used at query time to convert text queries into visual
    embedding space for kNN search against frame-level visual embeddings.

    Singleton access via ``get_visual_embedding_service()`` (@lru_cache).
    """

    _QUERY_CACHE_SIZE = 128

    def __init__(self) -> None:
        self.settings = get_settings()
        self._model: "SiglipTextModel | None" = None
        self._tokenizer: Any = None
        self._dtype: "torch.dtype | None" = None
        self._query_cache: dict[str, list[float]] = {}
        self._query_cache_order: list[str] = []

    def _load_model(self) -> bool:
        """Lazy-load SigLIP2 text encoder on first use.

        Returns True if real model loaded, False if mock mode.
        """
        if self._model is not None:
            return True

        if self.settings.embedding_use_mock:
            logger.info("visual_embedding_mock_mode", reason="EMBEDDING_USE_MOCK=true")
            return False

        logger.info(
            "loading_visual_embedding_model",
            model=_SIGLIP2_MODEL_NAME,
        )

        import torch
        from transformers import AutoTokenizer, SiglipTextModel

        self._dtype = torch.bfloat16
        self._tokenizer = AutoTokenizer.from_pretrained(_SIGLIP2_MODEL_NAME)
        self._model = SiglipTextModel.from_pretrained(
            _SIGLIP2_MODEL_NAME,
            torch_dtype=self._dtype,
            low_cpu_mem_usage=True,
        )
        self._model.eval()

        logger.info(
            "visual_embedding_model_loaded",
            model=_SIGLIP2_MODEL_NAME,
            dtype=str(self._dtype),
            params_m=round(sum(p.numel() for p in self._model.parameters()) / 1e6, 1),
        )
        return True

    def embed_query(self, query: str) -> list[float]:
        """Encode a text query into 768-dim SigLIP2 visual embedding space.

        Results are LRU-cached (128 entries) since inference is ~200-400ms on CPU.
        """
        cached = self._query_cache.get(query)
        if cached is not None:
            return cached

        if self.settings.embedding_use_mock:
            result = _generate_mock_visual_embedding(query)
        else:
            loaded = self._load_model()
            if not loaded:
                result = _generate_mock_visual_embedding(query)
            else:
                result = self._encode_text(query)

        # LRU eviction
        if len(self._query_cache_order) >= self._QUERY_CACHE_SIZE:
            evicted = self._query_cache_order.pop(0)
            self._query_cache.pop(evicted, None)
        self._query_cache[query] = result
        self._query_cache_order.append(query)

        return result

    def _encode_text(self, text: str) -> list[float]:
        """Run text through SigLIP2 text encoder → L2-normalized 768-dim vector."""
        import torch
        import torch.nn.functional as F

        assert self._model is not None
        assert self._tokenizer is not None

        inputs = self._tokenizer(
            text,
            padding="max_length",
            max_length=_SIGLIP2_MAX_LENGTH,
            truncation=True,
            return_tensors="pt",
        )

        # Move inputs to same dtype (attention mask stays long)
        if self._dtype is not None:
            for key in inputs:
                if inputs[key].dtype == torch.float32:
                    inputs[key] = inputs[key].to(self._dtype)

        with torch.no_grad():
            outputs = self._model(**inputs)

        # pooler_output: EOS hidden → linear projection → [1, 768]
        pooled = outputs.pooler_output.float()  # Cast back to float32 for normalization
        normalized = F.normalize(pooled, p=2, dim=-1)

        return normalized.squeeze(0).tolist()


@lru_cache(maxsize=1)
def get_visual_embedding_service() -> VisualEmbeddingService:
    """Get the singleton visual embedding service instance."""
    return VisualEmbeddingService()


async def get_visual_query_embedding(query: str) -> list[float]:
    """Get SigLIP2 visual embedding for a search query.

    Main entry point used by the search service.
    Returns 768-dim L2-normalized vector in SigLIP2 visual space.
    """
    service = get_visual_embedding_service()
    return service.embed_query(query)


def _generate_mock_visual_embedding(text: str) -> list[float]:
    """Generate deterministic mock 768-dim embedding for testing.

    Uses a different hash seed than the E5 mock to ensure text and visual
    mock embeddings are distinguishable.
    """
    # Prefix with "visual:" to produce different vectors than E5 mock
    hash_bytes = hashlib.md5(f"visual:{text}".encode("utf-8")).digest()

    embedding: list[float] = []
    for i in range(VISUAL_EMBEDDING_DIMENSION):
        seed_bytes = hash_bytes + struct.pack("I", i)
        hash_val = hashlib.md5(seed_bytes).digest()
        int_val = int.from_bytes(hash_val[:4], byteorder="little", signed=False)
        normalized = (int_val / (2**32 - 1)) * 2.0 - 1.0
        embedding.append(normalized)

    # L2 normalize
    norm = math.sqrt(sum(x * x for x in embedding))
    if norm > 0:
        embedding = [x / norm for x in embedding]

    return embedding
