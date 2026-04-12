"""
GPU reranker HTTP service.

Stateless FastAPI service that scores query-document pairs using a
cross-encoder model on GPU. Called synchronously by the Heimdex API
during search to rerank RRF fusion results.

No Heimdex domain dependencies — pure scoring function.
"""
from __future__ import annotations

import os
import time

import structlog
import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from transformers import AutoModelForSequenceClassification, AutoTokenizer

logger = structlog.get_logger(__name__)

# --- Configuration from environment ---
RERANKER_MODEL = os.environ.get("RERANKER_MODEL", "BAAI/bge-reranker-base")
MAX_DOCUMENTS = int(os.environ.get("RERANKER_MAX_DOCUMENTS", "100"))
MAX_LENGTH = int(os.environ.get("RERANKER_MAX_LENGTH", "512"))

# --- Global model state (loaded once at startup) ---
_tokenizer = None
_model = None
_device = None


def _load_model() -> None:
    global _tokenizer, _model, _device

    _device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info("loading_reranker_model", model=RERANKER_MODEL, device=_device)

    _tokenizer = AutoTokenizer.from_pretrained(RERANKER_MODEL)
    _model = AutoModelForSequenceClassification.from_pretrained(RERANKER_MODEL)
    _model.to(_device)
    _model.eval()

    param_count = sum(p.numel() for p in _model.parameters())
    logger.info(
        "reranker_model_loaded",
        model=RERANKER_MODEL,
        device=_device,
        parameters=f"{param_count / 1e6:.1f}M",
    )


# --- Schemas ---
class RerankRequest(BaseModel):
    query: str
    documents: list[str] = Field(max_length=MAX_DOCUMENTS)


class RerankResponse(BaseModel):
    scores: list[float]
    model: str
    latency_ms: float


class HealthResponse(BaseModel):
    status: str
    model: str
    gpu_available: bool
    device: str


# --- App ---
app = FastAPI(title="Heimdex Reranker Service")


@app.on_event("startup")
def startup() -> None:
    _load_model()


@app.post("/rerank", response_model=RerankResponse)
def rerank(request: RerankRequest) -> RerankResponse:
    if not request.documents:
        return RerankResponse(scores=[], model=RERANKER_MODEL, latency_ms=0.0)

    if len(request.documents) > MAX_DOCUMENTS:
        raise HTTPException(
            status_code=422,
            detail=f"Too many documents: {len(request.documents)} > {MAX_DOCUMENTS}",
        )

    t0 = time.monotonic()

    pairs = [[request.query, doc] for doc in request.documents]
    inputs = _tokenizer(
        pairs,
        padding=True,
        truncation=True,
        max_length=MAX_LENGTH,
        return_tensors="pt",
    ).to(_device)

    with torch.no_grad():
        if _device == "cuda":
            with torch.cuda.amp.autocast():
                logits = _model(**inputs).logits.squeeze(-1)
        else:
            logits = _model(**inputs).logits.squeeze(-1)

    scores = torch.sigmoid(logits).cpu().tolist()
    if isinstance(scores, float):
        scores = [scores]

    latency_ms = (time.monotonic() - t0) * 1000

    logger.info(
        "reranker_inference_complete",
        query=request.query[:50],
        document_count=len(request.documents),
        latency_ms=round(latency_ms, 1),
        top_score=round(max(scores), 4) if scores else None,
    )

    return RerankResponse(scores=scores, model=RERANKER_MODEL, latency_ms=latency_ms)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok" if _model is not None else "loading",
        model=RERANKER_MODEL,
        gpu_available=torch.cuda.is_available(),
        device=_device or "unknown",
    )
