# Phase A — Vision Caption Evidence Gathering

**Date:** 2026-02-20
**Status:** Complete
**Purpose:** Document all codebase evidence needed to design a Vision-First Scene Captioning feature.

---

## A1. Scene Schema & Ingest Pipeline

### Contracts (heimdex-media-contracts)

**`IngestSceneDocument`** — `ingest/schemas.py:15-45`
```python
class IngestSceneDocument(BaseModel):
    scene_id: str
    start_ms: int
    end_ms: int
    transcript_raw: Optional[str] = None
    speech_segment_count: Optional[int] = None
    ocr_text_raw: Optional[str] = None
    ocr_char_count: Optional[int] = None
    source_type: str = "agent"
    # ... 15 fields total
```

**`SceneDocument`** — `scenes/schemas.py:51-94`
- Higher-level scene representation used by pipelines.
- Includes `SceneBoundary` (start_ms, end_ms, keyframe_timestamp_ms).

**New field location:** Add `scene_caption: Optional[str] = None` to `IngestSceneDocument`. Backward compatible — existing ingest payloads without this field continue working.

### SaaS Ingest Service

**`SceneIngestService.ingest_scenes()`** — `api/app/modules/ingest/service.py:53-213`

Pipeline:
1. Validate library ownership (library_id → org_id)
2. Normalize `transcript_raw` → `transcript_norm` (SaaS-side normalization)
3. Normalize `ocr_text_raw` → `ocr_text_norm`
4. Build embedding text: `transcript_norm + " " + ocr_norm`
5. Batch embed via `intfloat/multilingual-e5-large` (1024-dim)
6. Build document with composite doc_id: `"{org_id}:{scene_id}"`
7. Bulk index to OpenSearch (upsert — same doc_id = full overwrite)

**Caption integration point:** After step 3, normalize `scene_caption` → `scene_caption_norm`. Optionally fold into embedding text at step 4 (decision deferred to Phase E).

### OpenSearch Mapping

**`scene_client.py:179-243`** — 26 fields currently mapped:

| Field | Type | Analyzer | Notes |
|-------|------|----------|-------|
| `transcript_norm` | text | korean_analyzer (Nori) | Primary search field |
| `transcript_raw` | text | standard | Fallback |
| `video_title` | text + `.nori` sub-field | korean_analyzer | Boosted 1.5x |
| `ocr_text_raw` | text | standard | Boosted 0.6x |
| `ocr_text_norm` | text | korean_analyzer | |
| `embedding_vector` | knn_vector | — | 1024-dim, cosine, HNSW |

**New mapping for caption:**
```python
"scene_caption": {"type": "text", "analyzer": "korean_analyzer"},
"scene_caption_raw": {"type": "text", "analyzer": "standard"},
```

Both fields use `text` type — BM25 searchable. No additional embedding call needed (preserves constraint: "do not increase per-scene embedding calls").

---

## A2. Representative Frames (Keyframes)

### Scene Detection

**`scenes/detector.py:92`** — Keyframe timestamp = midpoint of scene:
```python
keyframe_timestamp_ms = start_ms + (end_ms - start_ms) // 2
```

### Keyframe Extraction

**`scenes/keyframe.py`** — ffmpeg extracts JPEG at `keyframe_timestamp_ms`:
```python
# Single frame extraction
ffmpeg -ss {timestamp_s} -i {video_path} -frames:v 1 -q:v 2 {output_path}
```

Batch mode supported: `extract_keyframes_batch()` processes multiple timestamps in one ffmpeg pass.

### S3 Storage

Keyframes stored by drive-worker at:
```
{org_id}/drive/keyframes/{video_id}/{scene_id}.jpg
```

S3 key function: `enrichment_keyframe_s3_key(org_id, video_id, scene_id)` in `drive/keys.py`.

### OCR Worker Frame Sampling

**`ocr.py`** — `select_keyframe_indices()` evenly spaces frames:
- Input: total scene count, max frames budget
- Output: list of indices (always includes first and last)
- Respects `DRIVE_OCR_MAX_FRAMES_PER_VIDEO` (default: 300)

**Reusable for captioning:** Same function can select which scenes get captioned. One keyframe per scene is sufficient for a 1-sentence caption — OCR evidence confirms single-frame quality is adequate.

---

## A3. Enrichment Worker Architecture

### Worker Lifecycle Pattern (OCR/STT/Drive)

All enrichment workers follow identical structure:

```
main() → load settings → create engine + session factory → load model once
       → APScheduler interval job → poll_and_process() every N seconds
       → signal handlers → asyncio event loop
```

**Key design points:**
- Model loaded ONCE at startup, reused across all jobs
- `max_instances=1` on scheduler prevents concurrent poll cycles
- Global concurrency counter limits parallel jobs (`_acquire_slot` / `_release_slot`)
- Config flags enable/disable: `DRIVE_OCR_ENABLED`, `DRIVE_STT_ENABLED`

### Job Claiming (Atomic)

```python
SELECT ... FROM drive_files
WHERE enrichment_state IN ('pending', 'failed_partial')
  AND ocr_status = 'pending'
  AND keyframe_s3_prefix IS NOT NULL
  AND is_deleted = FALSE
ORDER BY created_at ASC
LIMIT 1
FOR UPDATE SKIP LOCKED
```

- `FOR UPDATE SKIP LOCKED` = atomic claim, no contention between worker replicas
- Status set to `"running"` before returning claimed file
- Flushed immediately to DB

### Processing Flow (OCR as template)

1. Download scene manifest from S3: `{org_id}/drive/manifests/{video_id}/scenes.json`
2. Select keyframe indices via `select_keyframe_indices()`
3. Download keyframes from S3: `{org_id}/drive/keyframes/{video_id}/{scene_id}.jpg`
4. Run OCR engine on each keyframe
5. Merge results into scene dicts (worker-side merge, not API-side)
6. Re-ingest via `POST /internal/ingest/scenes` with full scene list
7. Update status to `"done"` in DB

### Re-Ingest API

**`POST /internal/ingest/scenes`** — `internal_router.py`

Auth: `Authorization: Bearer {DRIVE_INTERNAL_API_KEY}`
Tenancy: `X-Heimdex-Org-Id` header
DoS protection: max scenes per request capped

Payload:
```json
{
  "video_id": "...",
  "video_title": "...",
  "library_id": "...",
  "total_duration_ms": 12345,
  "scenes": [
    {
      "scene_id": "...",
      "start_ms": 0,
      "end_ms": 5000,
      "transcript_raw": "...",
      "ocr_text_raw": "...",
      "scene_caption": "NEW FIELD"
    }
  ]
}
```

**Behavior:** Full overwrite per doc_id. Workers must pass ALL scene fields (not just enriched ones) because the API builds a complete document for OpenSearch upsert.

### Enrichment State Machine

**DriveFile model columns:**
| Column | Values | Notes |
|--------|--------|-------|
| `enrichment_state` | pending / running / done / failed_partial / failed | Computed from sub-statuses |
| `stt_status` | pending / running / done / failed | |
| `ocr_status` | pending / running / done / failed | |

**State computation:** `_compute_enrichment_state(stt_status, ocr_status)`:
- All `"done"` → `"done"`
- Mixed done+failed → `"failed_partial"`
- All failed → `"failed"`
- Any running → `"running"`
- Default → `"pending"`

**Caption extension:** Add `caption_status` column. Update `_compute_enrichment_state()` to include it as a third input.

### Error Handling

- Worker catches all exceptions → sets status to `"failed"` with error message
- Temp directory cleaned in `finally` block
- Session rolled back on exception
- **No automatic retry** — must manually set status back to `"pending"` to retry
- Non-200 from `/internal/ingest/scenes` → RuntimeError → caught → status `"failed"`

### Docker Compose

```yaml
drive-ocr-worker:
  environment:
    - DRIVE_OCR_ENABLED=${DRIVE_OCR_ENABLED:-false}
    - DRIVE_INTERNAL_API_KEY=${DRIVE_INTERNAL_API_KEY:-}
    - DRIVE_API_BASE_URL=http://api:8000
    - DRIVE_S3_BUCKET=${DRIVE_S3_BUCKET:-heimdex-drive}
    - DRIVE_OCR_POLL_INTERVAL_SECONDS=${DRIVE_OCR_POLL_INTERVAL_SECONDS:-30}
    - DRIVE_OCR_CONCURRENCY=${DRIVE_OCR_CONCURRENCY:-1}
  volumes:
    - ./services/drive-ocr-worker:/app
    - ./services/api:/opt/heimdex-api:ro          # Shared settings
    - ../heimdex-media-contracts:/opt/heimdex-media-contracts:ro
    - ../heimdex-media-pipelines:/opt/heimdex-media-pipelines:ro
  depends_on: [postgres, minio, api]
  command: >
    sh -c "pip install --no-deps -e /opt/heimdex-media-contracts 2>/dev/null;
           pip install --no-deps -e /opt/heimdex-media-pipelines 2>/dev/null;
           python -m src.worker"
```

**Caption worker** would follow identical pattern with `DRIVE_CAPTION_ENABLED`, `DRIVE_CAPTION_POLL_INTERVAL_SECONDS`, `DRIVE_CAPTION_CONCURRENCY` env vars and a `vision_model_cache` volume for persistent model storage.

---

## A4. Pipelines Repo Structure

### Existing Layout

```
heimdex-media-pipelines/src/heimdex_media_pipelines/
├── ocr/          # PaddleOCR (engine.py, pipeline.py, cli.py, __init__.py)
├── speech/       # Faster-Whisper (engine.py, pipeline.py)
├── faces/        # Face detection
├── scenes/       # Scene detection + keyframe extraction
├── transcoding/  # Video transcoding
└── __init__.py
```

### Engine Pattern (OCR as reference)

```python
# ocr/engine.py
class OCREngine(Protocol):
    def detect(self, image_path: str) -> list[OCRBlock]: ...

class PaddleOCREngine:
    def __init__(self, lang: str = "korean", use_gpu: bool = False):
        self._ocr = PaddleOCR(use_angle_cls=True, lang=lang, use_gpu=use_gpu)

    def detect(self, image_path: str) -> list[OCRBlock]:
        result = self._ocr.ocr(image_path, cls=True)
        return [OCRBlock(text=..., confidence=..., bbox=...) for ...]

# Factory function
def create_ocr_engine(lang: str = "korean", use_gpu: bool = False) -> OCREngine:
    return PaddleOCREngine(lang=lang, use_gpu=use_gpu)
```

### Recommended Caption Module

```
heimdex-media-pipelines/src/heimdex_media_pipelines/
├── vision/                    # NEW MODULE
│   ├── __init__.py           # Exports: CaptionEngine, create_caption_engine
│   ├── engine.py             # Protocol + implementations (BLIP, Florence-2, etc.)
│   ├── pipeline.py           # batch_caption_frames(engine, frame_paths) → list[str]
│   └── cli.py                # CLI for testing: python -m heimdex_media_pipelines.vision.cli
```

### Optional Dependencies (pyproject.toml)

Existing pattern:
```toml
[project.optional-dependencies]
ocr = ["paddleocr>=2.8.0", "paddlepaddle>=2.6.1"]
speech = ["faster-whisper>=1.0.0"]
faces = ["deepface>=0.0.80"]
```

New:
```toml
vision = ["transformers>=4.36.0", "torch>=2.0.0", "Pillow>=10.0.0"]
```

### No Existing Caption Module

Confirmed: No `visual_summary`, `caption`, or VLM-related code exists in current `heimdex-media-pipelines`. The older repos (`heimdex-backend-ai-service`, `demo-heimdex-v3`) used OpenAI API for `visual_summary` — our design replaces that with local models.

---

## A5. UI Rendering (SceneCard)

### Current Layout

**`SearchResults.tsx:280-355`** — SceneCard structure:
```
┌─────────────────────────────────┐
│  Thumbnail (keyframe image)     │
├─────────────────────────────────┤
│  Video Title                    │
│  Transcript snippet             │
│  OCR text snippet               │  ← Caption inserts HERE
│  Quality bar (confidence score) │
│  Action buttons                 │
└─────────────────────────────────┘
```

### Caption Insertion Point

After OCR snippet (line 327), before quality bar (line 329):
```tsx
{result.scene_caption && (
  <p className="text-xs text-gray-500 mt-1 line-clamp-2">
    🎬 {result.scene_caption}
  </p>
)}
```

### TypeScript Type

**`search.ts`** — Add to `SceneResult` interface:
```typescript
scene_caption?: string;
```

### Other UI Locations

- **`VideoDetailPage.tsx`** — Scene list in video detail view. Caption would appear under each scene's transcript.
- **`DashboardContent.tsx`** — Dashboard aggregates. No caption display needed here.

---

## A6. Prior Art in Heimdex

### Older Repos (NOT in current codebase)

| Repo | Field | Model | Notes |
|------|-------|-------|-------|
| `heimdex-backend-ai-service` | `visual_summary` | OpenAI GPT-4V | Paid API, $0.01/frame |
| `demo-heimdex-v3` | `visual_summary` | OpenAI GPT-4V | Same |
| `heimdex-for-law-dev` | `visual_summary` | OpenAI GPT-4V | Same |

**Current livecommerce repo:** No visual summary. Clean slate.

**Design constraint:** Must NOT use paid AI APIs. Local CPU-first model replaces OpenAI.

---

## Summary: Integration Points for Caption Feature

| Layer | File | Change |
|-------|------|--------|
| **Contracts** | `ingest/schemas.py` | Add `scene_caption: Optional[str]` to `IngestSceneDocument` |
| **Pipelines** | New `vision/` module | `CaptionEngine` protocol + implementation |
| **Pipelines** | `pyproject.toml` | Add `[vision]` optional dependency group |
| **SaaS Ingest** | `service.py` | Normalize caption, optionally include in embedding text |
| **SaaS Mapping** | `scene_client.py` | Add `scene_caption` + `scene_caption_raw` fields |
| **SaaS Search** | `scene_service.py` | Include `scene_caption` in BM25 multi-match query |
| **SaaS Schema** | `search/schemas.py` | Add `scene_caption` to `SceneResult` response |
| **DB Model** | `drive/models.py` | Add `caption_status` column to `DriveFile` |
| **DB Repo** | `drive/repository.py` | Add `claim_caption_pending_files()`, update state machine |
| **Worker** | New `drive-caption-worker/` | Full worker service (copy OCR worker pattern) |
| **Docker** | `docker-compose.yml` | Add `drive-caption-worker` service definition |
| **Config** | `config.env` | Add `DRIVE_CAPTION_ENABLED`, poll interval, concurrency |
| **UI** | `SearchResults.tsx` | Render caption in SceneCard |
| **UI Types** | `search.ts` | Add `scene_caption?: string` to `SceneResult` |
