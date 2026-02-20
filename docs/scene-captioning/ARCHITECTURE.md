# Phase D — Architecture Proposal

**Date:** 2026-02-20
**Status:** Complete
**Purpose:** Concrete architecture for the scene caption enrichment worker, data flow, and failure handling.

---

## Architecture Decision: New Worker Service

### Options Considered

| Option | Pros | Cons | Decision |
|--------|------|------|----------|
| **A: New `drive-caption-worker`** | Clean separation, independent scaling, no risk to OCR/STT | One more Docker service to manage | **Selected** |
| B: Integrate into OCR worker | Fewer services, share keyframe downloads | OCR + VLM compete for RAM (~4.5 GB combined), slower OCR poll cycle | Rejected |
| C: Agent-side captioning | No server cost, works offline | Increases agent binary size 2 GB+, inconsistent model versions, Go + Python bridge complexity | Rejected |

**Rationale:** Following the established enrichment worker pattern exactly (see Phase A, Section A3). Each enrichment type is an independent Docker service with its own concurrency control, feature flag, and model lifecycle. This is how OCR and STT workers are structured.

---

## Data Flow

```
┌─────────────────┐
│   drive-worker   │  Uploads keyframes to S3, creates scene manifest
│  (existing)      │  Sets enrichment_state="pending", caption_status="pending"
└────────┬────────┘
         │  S3: {org_id}/drive/keyframes/{video_id}/{scene_id}.jpg
         │  S3: {org_id}/drive/manifests/{video_id}/scenes.json
         ▼
┌─────────────────────┐
│  drive-stt-worker    │  Transcribes audio → re-ingests with transcript
│  drive-ocr-worker    │  OCRs keyframes → re-ingests with ocr_text
│  (existing, run      │
│   before caption)    │
└────────┬────────────┘
         │  DB: stt_status="done", ocr_status="done"
         ▼
┌─────────────────────┐
│  drive-caption-worker │  ◀── NEW SERVICE
│                       │
│  1. Poll DB for       │  SELECT ... WHERE caption_status='pending'
│     pending files     │    AND (ocr_status='done' OR stt_status='done')
│                       │    FOR UPDATE SKIP LOCKED
│  2. Download manifest │  S3: {org_id}/drive/manifests/{video_id}/scenes.json
│     from S3           │
│  3. Download keyframes│  S3: {org_id}/drive/keyframes/{video_id}/{scene_id}.jpg
│     from S3           │
│  4. Check pHash cache │  Redis: caption:{model_ver}:{phash} → cached caption
│                       │
│  5. Run InternVL2-1B  │  Model loaded once at startup, reused
│     on uncached frames│  max_num=1, num_beams=1, max_new_tokens=64
│                       │
│  6. Merge captions    │  Worker-side: scene_dict["scene_caption"] = caption
│     into scene dicts  │
│  7. Re-ingest via API │  POST /internal/ingest/scenes
│                       │    Authorization: Bearer {DRIVE_INTERNAL_API_KEY}
│                       │    X-Heimdex-Org-Id: {org_id}
│  8. Update DB status  │  caption_status="done"
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  API (ingest service)│  Normalizes caption, indexes to OpenSearch
│  (existing)          │  Doc ID: "{org_id}:{scene_id}" (upsert)
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  OpenSearch          │  scene_caption field searchable via BM25
│  (existing)          │  korean_analyzer for Korean captions
└─────────────────────┘
```

---

## Worker Implementation

### Directory Structure

```
services/drive-caption-worker/
├── Dockerfile
├── requirements.txt
└── src/
    ├── __init__.py
    ├── worker.py              # Entry point: main(), scheduler, signal handlers
    ├── tasks/
    │   ├── __init__.py
    │   └── caption.py         # process_caption_pending_files(), _process_single_caption()
    └── cache.py               # pHash-based caption cache (Redis)
```

### Worker Entry Point (`worker.py`)

```python
import asyncio
import signal
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# Import shared settings from API (mounted read-only)
from app.config import get_settings
from tasks.caption import process_caption_pending_files

# Model loaded ONCE at module level
_caption_engine = None

def _load_caption_engine(settings):
    """Load InternVL2-1B once at startup. ~2.5 GB RAM, ~15s load time."""
    import torch
    from transformers import AutoModel, AutoTokenizer
    
    model = AutoModel.from_pretrained(
        "OpenGVLab/InternVL2-1B",
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
    ).eval()
    tokenizer = AutoTokenizer.from_pretrained(
        "OpenGVLab/InternVL2-1B",
        trust_remote_code=True,
    )
    return model, tokenizer

async def poll_and_process(session_factory):
    settings = get_settings()
    if not settings.drive_caption_enabled:
        return
    if not _acquire_slot(settings):
        return
    
    async with session_factory() as session:
        try:
            await process_caption_pending_files(
                session, settings, _caption_engine
            )
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("caption_poll_cycle_failed")
        finally:
            _release_slot()

def main():
    settings = get_settings()
    
    # 1. Load model once
    global _caption_engine
    _caption_engine = _load_caption_engine(settings)
    
    # 2. Create DB session factory
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    # 3. Schedule polling
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        poll_and_process,
        "interval",
        seconds=settings.drive_caption_poll_interval_seconds,
        args=[session_factory],
        max_instances=1,
        id="caption_poll",
    )
    scheduler.start()
    
    # 4. Graceful shutdown
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: scheduler.shutdown(wait=False))
    
    loop.run_forever()

if __name__ == "__main__":
    main()
```

### Caption Task (`tasks/caption.py`)

```python
import json
import shutil
import tempfile
from pathlib import Path
from PIL import Image
import torch

from app.modules.drive.repository import DriveFileRepository
from app.modules.drive.keys import scene_manifest_s3_key, enrichment_keyframe_s3_key
from app.storage.s3 import S3Client
from cache import CaptionCache

CAPTION_PROMPT = "<image>\n이 장면을 한 문장으로 설명해주세요."

async def process_caption_pending_files(session, settings, caption_engine):
    file_repo = DriveFileRepository(session)
    files = await file_repo.claim_caption_pending_files(limit=1)
    
    for drive_file in files:
        await _process_single_caption(
            session, settings, drive_file, file_repo, caption_engine
        )

async def _process_single_caption(session, settings, drive_file, file_repo, caption_engine):
    model, tokenizer = caption_engine
    org_id_str = str(drive_file.org_id)
    video_id = drive_file.video_id
    temp_dir = Path(tempfile.mkdtemp(prefix=f"caption_{video_id}_"))
    cache = CaptionCache(settings)
    
    try:
        s3 = S3Client(bucket=settings.drive_s3_bucket)
        
        # 1. Download scene manifest
        manifest_key = scene_manifest_s3_key(org_id_str, video_id)
        manifest_path = temp_dir / "scenes.json"
        s3.download_file(manifest_key, manifest_path)
        manifest = json.loads(manifest_path.read_text())
        scenes = manifest.get("scenes", [])
        
        # 2. Download keyframes and caption each scene
        keyframes_dir = temp_dir / "keyframes"
        keyframes_dir.mkdir()
        
        for i, scene in enumerate(scenes):
            scene_id = scene.get("scene_id")
            s3_key = enrichment_keyframe_s3_key(org_id_str, video_id, scene_id)
            local_path = keyframes_dir / f"{scene_id}.jpg"
            
            try:
                s3.download_file(s3_key, local_path)
            except Exception:
                logger.warning("caption_keyframe_download_failed", scene_id=scene_id)
                continue
            
            # 3. Check cache
            frame = Image.open(local_path).convert("RGB")
            cached = cache.get(frame)
            if cached:
                scene["scene_caption"] = cached
                continue
            
            # 4. Run inference
            caption = _generate_caption(model, tokenizer, frame)
            scene["scene_caption"] = caption
            
            # 5. Store in cache
            cache.put(frame, caption)
        
        # 6. Re-ingest via internal API
        _post_scenes_to_api(
            settings=settings,
            org_id=drive_file.org_id,
            video_id=video_id,
            video_title=manifest.get("video_title"),
            library_id=manifest.get("library_id"),
            duration_ms=manifest.get("total_duration_ms"),
            scenes=scenes,
        )
        
        # 7. Update status
        await file_repo.update_caption_enrichment_status(
            drive_file.id, caption_status="done"
        )
        
    except Exception as e:
        await file_repo.update_caption_enrichment_status(
            drive_file.id,
            caption_status="failed",
            enrichment_error=str(e),
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _generate_caption(model, tokenizer, frame: Image.Image) -> str:
    """Run InternVL2-1B on a single frame. CPU-optimized."""
    from internvl2_utils import load_image_tensor  # custom preprocessing
    
    pixel_values = load_image_tensor(frame, max_num=1)  # single tile
    
    generation_config = dict(
        max_new_tokens=64,
        num_beams=1,
        do_sample=False,
    )
    
    with torch.no_grad():
        response = model.chat(
            tokenizer, pixel_values, CAPTION_PROMPT, generation_config
        )
    
    return response.strip()[:500]  # Truncate safety
```

---

## Model Singleton & Memory Management

### Startup Sequence

```
Worker starts
  → Load InternVL2-1B (15s, 2.5 GB RAM)
  → model.eval()  (disable dropout/gradients)
  → Start scheduler
  → Poll every 30s
```

### Memory Safety

| Rule | Implementation |
|------|----------------|
| Model loaded once | Global `_caption_engine` set in `main()` |
| No gradient accumulation | `model.eval()` + `torch.no_grad()` context |
| Temp files cleaned | `shutil.rmtree(temp_dir)` in `finally` |
| PIL images closed | Garbage collected after each scene (Python ref counting) |
| Model never unloaded | Stays in memory for worker lifetime |

### OOM Protection

```python
# In worker.py, after model load
import resource
rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # macOS: bytes, Linux: KB
if rss_mb > 3500:  # 3.5 GB threshold
    logger.error("caption_worker_memory_exceeded", rss_mb=rss_mb)
    sys.exit(1)  # Let Docker restart policy handle it
```

---

## Database Changes

### New Column on `DriveFile`

```python
# Alembic migration
op.add_column('drive_files', sa.Column('caption_status', sa.String(20), server_default='pending'))
op.add_column('drive_files', sa.Column('caption_error', sa.Text(), nullable=True))
op.add_column('drive_files', sa.Column('caption_updated_at', sa.DateTime(timezone=True), nullable=True))
```

### Updated State Machine

```python
def _compute_enrichment_state(
    stt_status: Optional[str],
    ocr_status: Optional[str],
    caption_status: Optional[str] = None,  # NEW — backward compatible
) -> str:
    active = [s for s in (stt_status, ocr_status, caption_status) if s is not None]
    if not active:
        return "pending"
    if all(s == "done" for s in active):
        return "done"
    if all(s in ("done", "failed") for s in active):
        return "failed" if all(s == "failed" for s in active) else "failed_partial"
    if any(s == "running" for s in active):
        return "running"
    return "pending"
```

### New Repository Method

```python
async def claim_caption_pending_files(self, limit: int = 1) -> list[DriveFile]:
    result = await self.session.execute(
        select(DriveFile)
        .where(
            DriveFile.caption_status == "pending",
            # Only caption after OCR + STT are done (or failed/null)
            or_(
                DriveFile.ocr_status.in_(["done", "failed"]),
                DriveFile.ocr_status.is_(None),
            ),
            or_(
                DriveFile.stt_status.in_(["done", "failed"]),
                DriveFile.stt_status.is_(None),
            ),
            DriveFile.keyframe_s3_prefix.isnot(None),
            DriveFile.is_deleted.is_(False),
        )
        .order_by(DriveFile.created_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    files = list(result.scalars().all())
    for f in files:
        f.caption_status = "running"
    if files:
        await self.session.flush()
    return files
```

---

## Docker Compose

```yaml
drive-caption-worker:
  build:
    context: ./services/drive-caption-worker
    dockerfile: Dockerfile
  container_name: heimdex-drive-caption-worker
  environment:
    - PYTHONPATH=/app:/opt/heimdex-api
    - DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER:-heimdex}:${POSTGRES_PASSWORD:-heimdex}@postgres:5432/${POSTGRES_DB:-heimdex}
    - MINIO_ENDPOINT=minio:9000
    - DRIVE_CAPTION_ENABLED=${DRIVE_CAPTION_ENABLED:-false}
    - DRIVE_INTERNAL_API_KEY=${DRIVE_INTERNAL_API_KEY:-}
    - DRIVE_API_BASE_URL=http://api:8000
    - DRIVE_S3_BUCKET=${DRIVE_S3_BUCKET:-heimdex-drive}
    - DRIVE_CAPTION_POLL_INTERVAL_SECONDS=${DRIVE_CAPTION_POLL_INTERVAL_SECONDS:-30}
    - DRIVE_CAPTION_CONCURRENCY=${DRIVE_CAPTION_CONCURRENCY:-1}
    - DRIVE_CAPTION_MODEL=${DRIVE_CAPTION_MODEL:-OpenGVLab/InternVL2-1B}
    - DRIVE_CAPTION_MODEL_VERSION=${DRIVE_CAPTION_MODEL_VERSION:-internvl2-1b-v1}
    - REDIS_URL=${REDIS_URL:-redis://redis:6379/0}
    - LOG_LEVEL=${LOG_LEVEL:-INFO}
    - HF_HOME=/data/hf-cache
  volumes:
    - ./services/drive-caption-worker:/app
    - ./services/api:/opt/heimdex-api:ro
    - ../heimdex-media-contracts:/opt/heimdex-media-contracts:ro
    - ../heimdex-media-pipelines:/opt/heimdex-media-pipelines:ro
    - caption_model_cache:/data/hf-cache    # Persistent model cache
  depends_on:
    postgres:
      condition: service_healthy
    minio:
      condition: service_healthy
    api:
      condition: service_healthy
    redis:
      condition: service_healthy
  command: >
    sh -c "pip install --no-deps -e /opt/heimdex-media-contracts 2>/dev/null;
           pip install --no-deps -e /opt/heimdex-media-pipelines 2>/dev/null;
           python -m src.worker"
  deploy:
    resources:
      limits:
        memory: 4G    # Hard cap: model (2.5G) + overhead (1.5G)

volumes:
  caption_model_cache:
```

---

## Failure Handling

| Failure | Detection | Recovery |
|---------|-----------|----------|
| Keyframe download fails | S3 exception in download loop | Skip scene, continue others. Log warning. |
| Model inference fails | Exception in `_generate_caption()` | Set `caption_status="failed"`, log error with traceback |
| Re-ingest API returns non-200 | RuntimeError from `_post_scenes_to_api()` | Set `caption_status="failed"`, error message saved to `caption_error` |
| Worker OOM | RSS > 3.5 GB check, or Docker kill | Docker `restart: unless-stopped`. Model reloads on restart. |
| DB connection lost | SQLAlchemy exception | Session rollback, status remains `"running"`. Next poll cycle sees stale `"running"` — needs manual reset to `"pending"`. |

### Stale "running" Recovery

If worker crashes mid-job, `caption_status` stays `"running"` indefinitely. Add a timeout check:

```python
# In claim query, also claim stale "running" jobs (stuck > 30 min)
.where(
    or_(
        DriveFile.caption_status == "pending",
        and_(
            DriveFile.caption_status == "running",
            DriveFile.caption_updated_at < (func.now() - timedelta(minutes=30)),
        ),
    ),
)
```

---

## Config Variables Summary

| Variable | Default | Description |
|----------|---------|-------------|
| `DRIVE_CAPTION_ENABLED` | `false` | Master switch |
| `DRIVE_CAPTION_POLL_INTERVAL_SECONDS` | `30` | DB poll interval |
| `DRIVE_CAPTION_CONCURRENCY` | `1` | Max parallel jobs |
| `DRIVE_CAPTION_MODEL` | `OpenGVLab/InternVL2-1B` | HuggingFace model ID |
| `DRIVE_CAPTION_MODEL_VERSION` | `internvl2-1b-v1` | Cache key component |
| `DRIVE_CAPTION_MAX_FRAMES_PER_VIDEO` | `300` | Frame budget (v2) |
| `DRIVE_CAPTION_SKIP_CACHE` | `false` | Force re-caption |
| `REDIS_URL` | `redis://redis:6379/0` | Cache backend |
