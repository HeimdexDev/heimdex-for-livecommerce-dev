# Phase C — Cost Control Strategy

**Date:** 2026-02-20
**Status:** Complete
**Purpose:** Prevent unbounded CPU cost from scene captioning. Design quotas, scope controls, and caching.

---

## Cost Profile

### Per-Frame Cost (InternVL2-1B on CPU)

| Metric | Value | Notes |
|--------|-------|-------|
| CPU time per frame | ~5-8s | `max_num=1`, greedy, `max_new_tokens=64` |
| RAM per worker | ~2.5-3 GB | bf16, single tile mode |
| Frames per video | 1 per scene | Reuses existing keyframes |
| Scenes per video (avg) | ~20 | Based on 15-video staging data (297 scenes / 15 = ~20) |
| **Total per video** | **~100-160s CPU** | 20 scenes x 5-8s each |

### Scaling Math

| Scale | Videos/day | Scenes/day | CPU hours/day | t3.xlarge cost/day |
|-------|-----------|------------|---------------|---------------------|
| Current (staging) | 1-2 | 40 | ~0.06h | $0.01 |
| Small org | 10 | 200 | ~0.33h | $0.06 |
| Medium org | 50 | 1,000 | ~1.7h | $0.28 |
| Large org (100 videos) | 100 | 2,000 | ~3.3h | $0.55 |
| Burst (500 videos/day) | 500 | 10,000 | ~16.7h | $2.78 |

At $0.1664/hr (t3.xlarge on-demand), captioning cost is negligible. **The risk is not monetary — it's worker saturation blocking other enrichment jobs.**

---

## Control Mechanisms

### 1. Feature Flag (Global Kill Switch)

```env
# config.env / .env
DRIVE_CAPTION_ENABLED=false          # Master switch — worker exits poll loop immediately
```

Same pattern as `DRIVE_OCR_ENABLED` and `DRIVE_STT_ENABLED`. When `false`, the caption worker's `poll_and_process()` returns immediately without DB queries.

### 2. Scope Control (Which Scenes Get Captioned)

**Default: Caption ALL scenes in a video.** Rationale: at 20 scenes/video and 5-8s/frame, a full video takes 2-3 minutes — acceptable.

**Future scope limits (not needed for v1, add if needed):**

```env
DRIVE_CAPTION_MAX_FRAMES_PER_VIDEO=50       # Cap for very long videos (100+ scenes)
DRIVE_CAPTION_MIN_SCENE_DURATION_MS=2000    # Skip scenes < 2s (likely transitions)
DRIVE_CAPTION_SKIP_IF_TRANSCRIPT=false      # Optional: skip if transcript already covers the scene
```

Frame selection reuses `select_keyframe_indices()` from OCR worker — already handles even sampling with budget cap.

### 3. Concurrency Control

```env
DRIVE_CAPTION_CONCURRENCY=1                 # Max parallel caption jobs per worker instance
DRIVE_CAPTION_POLL_INTERVAL_SECONDS=30      # Poll DB every 30s for pending work
```

Worker uses the same `_acquire_slot` / `_release_slot` pattern as OCR/STT workers. With `CONCURRENCY=1`, only one video is captioned at a time. Scale by adding worker replicas in docker-compose, not by increasing concurrency (model is memory-bound, not CPU-bound).

### 4. Quota System (Per-Org, Per-Day)

**Not needed for v1.** Current usage is single-org staging. Design for future:

```python
# Future: rate limiting at the API or worker level
DRIVE_CAPTION_MAX_VIDEOS_PER_ORG_PER_DAY=100
DRIVE_CAPTION_MAX_SCENES_PER_ORG_PER_DAY=5000
```

Implementation: counter in Redis (`caption:quota:{org_id}:{date}`) checked before claiming job. If exceeded, skip org's files until next day.

---

## Caching Strategy

### Frame Deduplication (pHash)

Livecommerce videos often have repeated static frames (product close-ups, branded overlays). Captioning identical frames wastes CPU.

**Approach:** Perceptual hash (pHash) of keyframe + model version as cache key.

```python
import imagehash
from PIL import Image

def make_caption_cache_key(frame: Image.Image, model_version: str) -> str:
    """pHash survives re-encoding, resize, minor edits."""
    ph = str(imagehash.phash(frame, hash_size=16))  # 256-bit hash
    return f"caption:{model_version}:{ph}"
```

### Cache Storage

**Option A: Redis (recommended for v1)**
- TTL: 30 days
- Key: `caption:{model_version}:{phash}`
- Value: caption string (typically < 200 bytes)
- Memory: 10K cached captions ≈ 5 MB

**Option B: PostgreSQL (future)**
- `caption_cache` table with `phash`, `model_version`, `caption`, `created_at`
- Survives Redis restarts
- Queryable for analytics

### Cache Invalidation

**When model changes:** model version is part of the cache key. Bumping `model_version` from `"internvl2-1b-v1"` to `"internvl2-1b-v2"` automatically misses all old cache entries. Old entries expire via TTL — no explicit purge needed.

**When to NOT cache:**
- If `DRIVE_CAPTION_SKIP_CACHE=true` is set (force re-caption for quality testing)
- During initial model validation (benchmark mode)

### Expected Cache Hit Rate

| Scenario | Expected Hit Rate | Reasoning |
|----------|-------------------|-----------|
| Single video, first ingest | 5-15% | Some static frames repeat across scenes |
| Re-ingest after OCR/STT | 100% | Same keyframes, already captioned |
| Cross-video (same org) | 10-30% | Branded overlays, recurring product shots |
| Cross-org | 0% | Different content entirely |

**Conservative estimate: 15% cache hit rate → 15% CPU savings.**

### pHash Collision Threshold

- Hamming distance <= 5 on 64-bit pHash = "same frame" (85%+ pixel similarity)
- For livecommerce: use threshold <= 3 (stricter) to avoid confusing similar product shots

```python
def is_duplicate(frame_phash, cached_hashes, threshold=3):
    return any((frame_phash - h) <= threshold for h in cached_hashes)
```

---

## Priority Ordering

Caption worker should run AFTER OCR and STT, not competing with them:

```
drive-worker (scene detection, keyframe extraction)
    ↓
drive-stt-worker (transcription — highest search value)
    ↓
drive-ocr-worker (text in frames — second highest)
    ↓
drive-caption-worker (visual description — supplementary)
```

**Implementation:** Caption worker claims files where `ocr_status = 'done'` AND `stt_status = 'done'` (or at least one is done). This ensures captioning doesn't compete with higher-value enrichments for the same file.

```python
# Claim query — only caption after OCR+STT complete
SELECT ... FROM drive_files
WHERE caption_status = 'pending'
  AND (ocr_status IN ('done', 'failed') OR ocr_status IS NULL)
  AND (stt_status IN ('done', 'failed') OR stt_status IS NULL)
  AND keyframe_s3_prefix IS NOT NULL
  AND is_deleted = FALSE
ORDER BY created_at ASC
LIMIT 1
FOR UPDATE SKIP LOCKED
```

---

## Monitoring

### Key Metrics (logged by worker)

| Metric | Log Field | Alert Threshold |
|--------|-----------|-----------------|
| Caption latency | `caption_latency_ms` | > 30s/frame (model may be swapping) |
| Cache hit rate | `caption_cache_hit` | < 5% (cache not working) |
| Worker memory | `worker_rss_mb` | > 3500 MB (approaching OOM) |
| Queue depth | `caption_pending_count` | > 100 (falling behind) |
| Error rate | `caption_error_count` | > 10% of jobs |

### Structured Log Example

```json
{
  "event": "caption_completed",
  "video_id": "abc123",
  "scenes_total": 20,
  "scenes_captioned": 17,
  "scenes_cached": 3,
  "total_latency_s": 102.5,
  "avg_latency_per_frame_s": 6.0,
  "model_version": "internvl2-1b-v1",
  "cache_hit_rate": 0.15
}
```

---

## Summary

| Control | V1 (Staging) | V2 (Production) |
|---------|-------------|-----------------|
| Feature flag | `DRIVE_CAPTION_ENABLED` | Same |
| Concurrency | 1 worker, 1 concurrent | Scale via replicas |
| Frame scope | All scenes | + min duration filter, frame budget |
| Caching | pHash + model version in Redis | + PostgreSQL persistence |
| Quotas | None | Per-org-per-day limits |
| Priority | After OCR + STT | Same |
| Monitoring | Structured logs | + Prometheus metrics |
