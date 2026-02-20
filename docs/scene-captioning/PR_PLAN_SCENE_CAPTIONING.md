# Phase F — PR Plan: Scene Captioning

**Date:** 2026-02-20
**Status:** Complete
**Purpose:** 5 atomic PRs to implement scene captioning end-to-end. Each PR is independently mergeable and testable.

---

## PR Dependency Graph

```
PR1 (contracts) ──► PR2 (pipelines) ──► PR3 (SaaS backend) ──► PR4 (worker) ──► PR5 (UI + search)
```

Each PR builds on the previous. PRs can be reviewed in parallel but must merge in order.

---

## PR1: Contracts — Add `scene_caption` to Schema

**Repo:** `jlee-heimdex/heimdex-media-contracts`
**Branch:** `feat/scene-caption-schema`
**Size:** ~20 lines changed

### Changes

| File | Change |
|------|--------|
| `src/heimdex_media_contracts/ingest/schemas.py` | Add `scene_caption: Optional[str] = None` to `IngestSceneDocument` |
| `tests/test_ingest_schemas.py` | Test that `scene_caption` is optional and defaults to None |

### Code

```python
# ingest/schemas.py
class IngestSceneDocument(BaseModel):
    scene_id: str
    start_ms: int
    end_ms: int
    transcript_raw: Optional[str] = None
    speech_segment_count: Optional[int] = None
    ocr_text_raw: Optional[str] = None
    ocr_char_count: Optional[int] = None
    scene_caption: Optional[str] = None  # NEW — vision-generated caption
    source_type: str = "agent"
```

### Tests

```python
def test_ingest_scene_document_without_caption():
    """Backward compat: existing payloads without scene_caption still parse."""
    doc = IngestSceneDocument(scene_id="s1", start_ms=0, end_ms=5000)
    assert doc.scene_caption is None

def test_ingest_scene_document_with_caption():
    doc = IngestSceneDocument(
        scene_id="s1", start_ms=0, end_ms=5000,
        scene_caption="진행자가 립스틱을 시연하고 있다."
    )
    assert doc.scene_caption == "진행자가 립스틱을 시연하고 있다."
```

### Acceptance Criteria

- [ ] `IngestSceneDocument` accepts `scene_caption` field
- [ ] Existing tests pass unchanged (backward compatible)
- [ ] New tests pass
- [ ] `pip install -e .` succeeds

---

## PR2: Pipelines — Vision Caption Engine

**Repo:** `jlee-heimdex/heimdex-media-pipelines`
**Branch:** `feat/vision-caption-engine`
**Size:** ~200 lines new code + tests

### Changes

| File | Change |
|------|--------|
| `src/heimdex_media_pipelines/vision/__init__.py` | Exports: `CaptionEngine`, `create_caption_engine` |
| `src/heimdex_media_pipelines/vision/engine.py` | `CaptionEngine` protocol + `InternVL2Engine` implementation |
| `src/heimdex_media_pipelines/vision/pipeline.py` | `batch_caption_frames(engine, frame_paths) -> list[str]` |
| `pyproject.toml` | Add `[vision]` optional dependency group |
| `tests/vision/test_engine.py` | Unit tests with mock model |
| `tests/vision/test_pipeline.py` | Integration test for batch captioning |

### Engine Protocol

```python
# vision/engine.py
from typing import Protocol
from PIL import Image

class CaptionEngine(Protocol):
    def caption(self, image: Image.Image, prompt: str = "") -> str:
        """Generate a caption for a single image."""
        ...

class InternVL2Engine:
    def __init__(self, model_id: str = "OpenGVLab/InternVL2-1B", use_gpu: bool = False):
        import torch
        from transformers import AutoModel, AutoTokenizer
        
        self.device = "cuda" if use_gpu and torch.cuda.is_available() else "cpu"
        dtype = torch.bfloat16 if self.device == "cuda" else torch.float32
        
        self.model = AutoModel.from_pretrained(
            model_id, torch_dtype=dtype, trust_remote_code=True
        ).to(self.device).eval()
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_id, trust_remote_code=True
        )
    
    def caption(self, image: Image.Image, prompt: str = "") -> str:
        if not prompt:
            prompt = "<image>\n이 장면을 한 문장으로 설명해주세요."
        # ... inference logic
        return response.strip()[:500]

def create_caption_engine(
    model_id: str = "OpenGVLab/InternVL2-1B",
    use_gpu: bool = False,
) -> CaptionEngine:
    return InternVL2Engine(model_id=model_id, use_gpu=use_gpu)
```

### Optional Dependencies

```toml
# pyproject.toml
[project.optional-dependencies]
ocr = ["paddleocr>=2.8.0", "paddlepaddle>=2.6.1"]
speech = ["faster-whisper>=1.0.0"]
faces = ["deepface>=0.0.80"]
vision = ["transformers>=4.36.0", "torch>=2.0.0", "Pillow>=10.0.0"]  # NEW
```

### Tests

```python
# tests/vision/test_engine.py
class MockCaptionEngine:
    def caption(self, image, prompt=""):
        return "A person demonstrating a product on camera."

def test_caption_engine_protocol():
    engine = MockCaptionEngine()
    result = engine.caption(Image.new("RGB", (224, 224)))
    assert isinstance(result, str)
    assert len(result) > 0

def test_caption_truncation():
    """Captions over 500 chars are truncated."""
    engine = create_test_engine_with_long_output()
    result = engine.caption(Image.new("RGB", (224, 224)))
    assert len(result) <= 500
```

### Acceptance Criteria

- [ ] `CaptionEngine` protocol matches `OCREngine` pattern
- [ ] `create_caption_engine()` factory works
- [ ] `pip install -e ".[vision]"` installs dependencies
- [ ] `pip install -e .` (without vision) still works (no import errors)
- [ ] All existing tests pass
- [ ] New tests pass with mock engine

---

## PR3: SaaS Backend — Ingest, Mapping, Search

**Repo:** `jlee-heimdex/dev-heimdex-for-livecommerce`
**Branch:** `feat/scene-caption-backend`
**Size:** ~150 lines changed across 6 files

### Changes

| File | Change |
|------|--------|
| `services/api/app/modules/ingest/service.py` | Normalize `scene_caption`, pass to OpenSearch doc |
| `services/api/app/modules/search/scene_client.py` | Add `scene_caption`, `scene_caption_raw` to mapping |
| `services/api/app/modules/search/scene_service.py` | Add `scene_caption` to BM25 multi-match (boost 1.0) |
| `services/api/app/modules/search/schemas.py` | Add `scene_caption: Optional[str]` to `SceneResult` |
| `services/api/app/modules/drive/models.py` | Add `caption_status`, `caption_error`, `caption_updated_at` columns |
| `services/api/app/modules/drive/repository.py` | Add `claim_caption_pending_files()`, `update_caption_enrichment_status()`, update `_compute_enrichment_state()` |
| Alembic migration | New migration for `caption_status` column |

### Ingest Service Change

```python
# service.py — in document builder loop
caption_norm = normalize_transcript(scene.scene_caption) if scene.scene_caption else ""

doc["scene_caption"] = scene.scene_caption or ""
doc["scene_caption_raw"] = scene.scene_caption or ""

# Embedding text UNCHANGED — no additional embedding call
embedding_text = f"{transcript_norm} {ocr_norm}".strip()
```

### Search Query Change

```python
# scene_service.py — add to BM25 should clause
{"match": {"scene_caption": {"query": q, "boost": 1.0}}},
```

### Tests

```python
# tests/api/test_ingest_with_caption.py
async def test_ingest_scenes_with_caption():
    payload = {
        "video_id": "v1",
        "scenes": [{
            "scene_id": "v1_scene_1",
            "start_ms": 0, "end_ms": 5000,
            "scene_caption": "진행자가 립스틱을 시연하고 있다.",
        }],
        ...
    }
    resp = await client.post("/internal/ingest/scenes", json=payload, ...)
    assert resp.status_code == 200

async def test_ingest_scenes_without_caption_backward_compat():
    payload = {
        "video_id": "v2",
        "scenes": [{"scene_id": "v2_scene_1", "start_ms": 0, "end_ms": 5000}],
        ...
    }
    resp = await client.post("/internal/ingest/scenes", json=payload, ...)
    assert resp.status_code == 200  # No error even without caption

async def test_search_matches_caption():
    # Ingest scene with caption "빨간 립스틱 시연"
    # Search for "립스틱"
    # Assert scene appears in results

async def test_claim_caption_pending_files():
    # Create DriveFile with caption_status="pending", ocr_status="done"
    # Claim → should return the file
    # Verify status changed to "running"

async def test_caption_waits_for_ocr_stt():
    # Create DriveFile with caption_status="pending", ocr_status="pending"
    # Claim → should return empty (OCR not done yet)
```

### Acceptance Criteria

- [ ] Ingest accepts `scene_caption` field (Optional)
- [ ] Existing ingest payloads without caption still work
- [ ] OpenSearch mapping includes `scene_caption` + `scene_caption_raw`
- [ ] BM25 search includes caption field with boost 1.0
- [ ] `SceneResult` response includes `scene_caption`
- [ ] `DriveFile` has `caption_status` column with state machine
- [ ] `claim_caption_pending_files()` respects OCR/STT completion ordering
- [ ] Alembic migration runs cleanly
- [ ] All 600+ existing tests pass
- [ ] New tests pass

---

## PR4: Caption Worker Service

**Repo:** `jlee-heimdex/dev-heimdex-for-livecommerce`
**Branch:** `feat/scene-caption-worker`
**Size:** ~400 lines new code + Dockerfile + docker-compose changes

### Changes

| File | Change |
|------|--------|
| `services/drive-caption-worker/Dockerfile` | Worker Docker image (Python 3.11 + torch + transformers) |
| `services/drive-caption-worker/requirements.txt` | Dependencies |
| `services/drive-caption-worker/src/__init__.py` | Package init |
| `services/drive-caption-worker/src/worker.py` | Entry point, scheduler, model loading |
| `services/drive-caption-worker/src/tasks/__init__.py` | Package init |
| `services/drive-caption-worker/src/tasks/caption.py` | Caption task: claim → download → caption → re-ingest |
| `services/drive-caption-worker/src/cache.py` | pHash-based caption cache (Redis) |
| `docker-compose.yml` | Add `drive-caption-worker` service definition |
| `config.env` | Add `DRIVE_CAPTION_ENABLED=false` and related vars |

### Docker Image Considerations

```dockerfile
FROM python:3.11-slim

# PyTorch CPU-only (no CUDA — saves ~2 GB image size)
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install transformers Pillow imagehash redis apscheduler sqlalchemy asyncpg

# Pre-download model at build time (optional — saves first-run latency)
# RUN python -c "from transformers import AutoModel, AutoTokenizer; \
#     AutoModel.from_pretrained('OpenGVLab/InternVL2-1B', trust_remote_code=True); \
#     AutoTokenizer.from_pretrained('OpenGVLab/InternVL2-1B', trust_remote_code=True)"

WORKDIR /app
COPY . /app

CMD ["python", "-m", "src.worker"]
```

### Tests

```python
# tests/drive_caption_worker/test_caption_task.py
async def test_process_single_caption_happy_path(mock_s3, mock_model, mock_api):
    """Full lifecycle: download manifest → download keyframes → caption → re-ingest."""
    mock_s3.setup_manifest(video_id="v1", scenes=3)
    mock_s3.setup_keyframes(video_id="v1", count=3)
    mock_model.return_value = "진행자가 제품을 시연하고 있다."
    
    await _process_single_caption(session, settings, drive_file, file_repo, (mock_model, mock_tokenizer))
    
    # Verify re-ingest was called with captions
    assert mock_api.called
    payload = mock_api.call_args[1]["json"]
    assert all(s.get("scene_caption") for s in payload["scenes"])
    
    # Verify status updated
    assert drive_file.caption_status == "done"

async def test_caption_cache_hit(mock_cache, mock_model):
    """Cached frames skip model inference."""
    mock_cache.get.return_value = "cached caption"
    
    await _process_single_caption(...)
    
    mock_model.assert_not_called()  # Model not invoked for cached frame

async def test_caption_keyframe_download_failure():
    """Missing keyframe skips scene, doesn't fail entire job."""
    mock_s3.setup_manifest(video_id="v1", scenes=3)
    mock_s3.setup_keyframes(video_id="v1", count=2)  # Scene 3 missing
    
    await _process_single_caption(...)
    
    # 2 of 3 scenes captioned, job still succeeds
    assert drive_file.caption_status == "done"
```

### Acceptance Criteria

- [ ] Worker starts and loads model successfully
- [ ] Poll cycle claims pending files correctly
- [ ] Downloads manifest and keyframes from S3
- [ ] pHash cache prevents re-captioning identical frames
- [ ] Re-ingest API called with caption-enriched scenes
- [ ] Status updated to "done" on success, "failed" on error
- [ ] Docker image builds and runs
- [ ] docker-compose up starts caption worker alongside existing services
- [ ] Worker respects `DRIVE_CAPTION_ENABLED=false` (does nothing)
- [ ] Graceful shutdown on SIGTERM

---

## PR5: UI — Display Caption in SceneCard

**Repo:** `jlee-heimdex/dev-heimdex-for-livecommerce`
**Branch:** `feat/scene-caption-ui`
**Size:** ~30 lines changed

### Changes

| File | Change |
|------|--------|
| `services/web/src/lib/types/search.ts` | Add `scene_caption?: string` to `SceneResult` |
| `services/web/src/features/search/components/SearchResults.tsx` | Render caption in SceneCard after OCR text |
| `services/web/src/features/videos/components/VideoDetailPage.tsx` | Render caption in scene list (if applicable) |

### UI Code

```tsx
// SearchResults.tsx — inside SceneCard, after OCR snippet (line ~327)
{result.scene_caption && (
  <p className="text-xs text-gray-500 mt-1 line-clamp-2">
    {result.scene_caption}
  </p>
)}
```

### TypeScript Type

```typescript
// search.ts
export interface SceneResult {
  // ... existing fields
  scene_caption?: string;
}
```

### Tests

```typescript
// __tests__/SearchResults.test.tsx
it('renders scene caption when present', () => {
  const result = { ...mockSceneResult, scene_caption: '진행자가 립스틱을 시연하고 있다.' };
  render(<SceneCard result={result} />);
  expect(screen.getByText('진행자가 립스틱을 시연하고 있다.')).toBeInTheDocument();
});

it('does not render caption section when absent', () => {
  const result = { ...mockSceneResult, scene_caption: undefined };
  render(<SceneCard result={result} />);
  // No caption element rendered
});
```

### Acceptance Criteria

- [ ] Caption displays in SceneCard when present
- [ ] No UI change when caption is absent (backward compatible)
- [ ] Caption text is truncated to 2 lines (line-clamp-2)
- [ ] TypeScript compiles without errors
- [ ] Existing UI tests pass
- [ ] New tests pass

---

## Implementation Timeline (Estimated)

| PR | Effort | Dependencies | Estimated Time |
|----|--------|-------------|---------------|
| PR1 (Contracts) | Small | None | 1 hour |
| PR2 (Pipelines) | Medium | PR1 | 3-4 hours |
| PR3 (SaaS Backend) | Medium | PR1 | 3-4 hours |
| PR4 (Worker) | Large | PR2 + PR3 | 6-8 hours |
| PR5 (UI) | Small | PR3 | 1-2 hours |
| **Total** | | | **~15-20 hours** |

PR2 and PR3 can be developed in parallel after PR1 merges.

---

## Rollback Plan

Each PR is independently revertable:

| PR | Rollback Impact |
|----|----------------|
| PR5 (UI) | Caption disappears from UI. No data loss. |
| PR4 (Worker) | No new captions generated. Existing captions remain in OpenSearch. |
| PR3 (Backend) | Captions stop being indexed. Existing indexed captions remain searchable until index rebuilt. |
| PR2 (Pipelines) | Vision module removed. Worker cannot load — set `DRIVE_CAPTION_ENABLED=false`. |
| PR1 (Contracts) | Schema field removed. Existing ingest payloads with `scene_caption` → ignored by Pydantic. |

**Emergency kill switch:** Set `DRIVE_CAPTION_ENABLED=false` in config.env → restarts caption worker → does nothing. Zero impact on other services.
