# Local Verification Procedure — Scene Captioning

## Prerequisites

- Python 3.11+ with venv
- Node.js 18+ with npm
- Docker Compose (for integration tests only)
- All 3 repos checked out at correct branches:
  - `heimdex-media-contracts` — main (commit `924fc7b`+)
  - `heimdex-media-pipelines` — main (commit `47d4351`+)
  - `dev-heimdex-for-livecommerce` — main (latest)

## Step 1: Contracts (PR1)

```bash
cd heimdex-media-contracts
source .venv/bin/activate
python -m pytest tests/ -v --tb=short
```

**Expected:** 242 passed, 0 failed.
**Key assertions:**
- `test_scene_caption_defaults_empty` — field exists, defaults to `""`
- `test_scene_caption_roundtrip` — Korean text preserved
- `test_scene_caption_max_length_rejected` — >5000 chars rejected
- `test_backward_compat_v1_data_without_new_fields` — old data still loads

## Step 2: Pipelines (PR2)

```bash
cd heimdex-media-pipelines
source .venv/bin/activate
python -m pytest tests/ -v --tb=short
```

**Expected:** 240 passed, 10 skipped, 0 failed.
**Key assertions:**
- `test_create_caption_engine_valid_models` — internvl2 and florence2 both instantiate
- `test_internvl2_caption_returns_caption_result_with_truncation` — output truncated at 500 chars
- `test_caption_returns_empty_result_on_error` — graceful degradation
- `test_lazy_load_model_once_for_both_engines` — singleton behavior

## Step 3: SaaS API (PR3)

```bash
cd dev-heimdex-for-livecommerce/services/api
source .venv/bin/activate
python -m pytest tests/ -v --tb=short
```

**Expected:** All existing tests pass + new `test_caption_enrichment.py` tests.
**Key assertions:**
- Config: `scene_caption_enabled` defaults to `False`
- `_compute_enrichment_state("done", "done", "done")` → `"done"`
- `_compute_enrichment_state("done", "done", None)` → `"done"` (backward compatible)
- `_compute_enrichment_state("done", "done", "failed")` → `"failed_partial"`
- SceneResult has `scene_caption` field defaulting to `""`

## Step 4: Frontend (PR5)

```bash
cd dev-heimdex-for-livecommerce/services/web
npx vitest run --reporter=verbose
```

**Expected:** All tests pass including 2 new scene_caption tests.
**Key assertions:**
- `scene_caption` renders in SceneCard when non-empty
- "AI 캡션" label NOT present when caption is empty

## Step 5: Caption Worker (PR4) — Structure Verification

```bash
# Verify directory structure exists
ls -la dev-heimdex-for-livecommerce/services/drive-caption-worker/
ls -la dev-heimdex-for-livecommerce/services/drive-caption-worker/src/
ls -la dev-heimdex-for-livecommerce/services/drive-caption-worker/src/tasks/

# Verify docker-compose has the service
grep -A 5 "drive-caption-worker" dev-heimdex-for-livecommerce/docker-compose.yml
```

**Expected:**
- `Dockerfile`, `pyproject.toml`, `src/worker.py`, `src/tasks/caption.py` exist
- `docker-compose.yml` has `drive-caption-worker` service with `SCENE_CAPTION_ENABLED=false`

## Step 6: Feature Flag Verification

1. **Default OFF:** `SCENE_CAPTION_ENABLED` not set → worker does nothing
2. **Config guard:** `Settings(scene_caption_enabled=False)` → no caption processing
3. **Backward compat:** Existing scenes without `scene_caption` field → search still works (field defaults to empty)

## Step 7: OpenSearch Mapping Verification (requires running cluster)

```bash
# After docker-compose up, check the index mapping includes scene_caption
curl -s localhost:9200/heimdex_scenes_v1/_mapping | python3 -m json.tool | grep scene_caption
```

**Expected:** `"scene_caption": { "type": "text", "analyzer": "korean_analyzer" ... }`

## Regression Surfaces

| Surface | What to check | How |
|---------|--------------|-----|
| Agent ingest | Scenes without caption still index normally | Existing agent ingest tests |
| Drive sync | Processing pipeline unchanged | `test_drive_scene_pipeline.py` |
| OCR worker | OCR enrichment unchanged | `test_ocr_worker_job_claiming.py` |
| STT worker | STT enrichment unchanged | `test_stt_worker_config.py` |
| BM25 search | Existing queries return same results | `test_search_quality.py` |
| Frontend | SceneCard renders without caption field | `SceneCard.test.tsx` |
| Multi-org | Tenant isolation preserved | `test_tenancy.py` |

## Kill Switch

If caption causes issues in production:

1. Set `SCENE_CAPTION_ENABLED=false` in config
2. Restart caption worker → it stops polling
3. Existing `scene_caption` data in OpenSearch is harmless (empty string or text)
4. BM25 clauses on empty field produce no matches — zero search impact
