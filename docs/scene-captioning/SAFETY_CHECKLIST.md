# Scene Captioning — Safety Checklist

**Created:** 2026-02-20
**Last verified:** 2026-02-21

---

## Kill Switch

| Variable | Default | Effect when `false` |
|----------|---------|---------------------|
| `SCENE_CAPTION_ENABLED` | `false` | Caption worker does nothing; SaaS behavior 100% unchanged |

---

## Regression Surfaces

| Surface | Risk | Verification | Status |
|---------|------|-------------|--------|
| **Agent ingest** | New optional field ignored by old agents | `pytest` contracts; ingest without `scene_caption` | ✅ 242 tests pass |
| **Drive sync** | DriveFile model change could break queries | Alembic migration + existing drive tests | ✅ Migration 014 applied on staging |
| **OCR enrichment** | State machine change could break OCR status | `_compute_enrichment_state` tests | ✅ 709 API tests pass |
| **STT enrichment** | State machine change could break STT status | `_compute_enrichment_state` tests | ✅ 709 API tests pass |
| **Search (BM25)** | New field in multi-match could degrade results | Existing search tests + manual golden queries | ✅ Verified on staging: "라이브커머스" returns 87 hits |
| **Search (vector)** | Embedding text must NOT change | Verify `embedding_text` construction unchanged | ✅ Code review: `embedding_text = f"{transcript_norm} {ocr_norm}".strip()` |
| **Thumbnails** | Keyframe S3 keys must not change | Verify `enrichment_keyframe_s3_key` unchanged | ✅ No changes to key functions |
| **Exports** | Export schemas must still serialize | contracts export tests | ✅ 242 contracts tests pass |
| **Multi-org tenancy** | Caption worker must scope by org_id | Internal endpoint requires `X-Heimdex-Org-Id` header | ✅ Verified on staging |
| **Multi-device** | Device registration unaffected | No device model changes | ✅ No changes |
| **UI rendering** | SceneCard must not break for scenes without captions | Conditional render `{result.scene_caption && ...}` | ✅ 166 web tests pass |

---

## Per-PR Verification

### PR1 — Contracts (`924fc7b`)
- [x] `pytest` in heimdex-media-contracts passes — 242/242 pass
- [x] `IngestSceneDocument` without `scene_caption` still parses (backward compat)
- [x] `IngestSceneDocument` with `scene_caption` parses correctly
- [x] `SceneDocument` without `scene_caption` still parses (backward compat)
- [x] `pip install -e .` succeeds

### PR2 — Pipelines (`47d4351` + `9e5af82`)
- [x] `pytest` in heimdex-media-pipelines passes — 240/240 pass, 10 skipped
- [x] `pip install -e .` succeeds (no vision deps required for base install)
- [x] `pip install -e ".[vision]"` installs vision dependencies
- [x] `CaptionEngine` protocol matches `OCREngine` pattern
- [x] Mock-based tests don't require HF model download

### PR3 — SaaS Backend (`d805c1f` + `1467e4a` + `7a7921a`)
- [x] `pytest` in dev-heimdex-for-livecommerce passes — 709/709 pass, 10 skipped
- [x] Alembic migration runs forward cleanly (migration 014 applied on staging)
- [ ] Alembic migration runs backward cleanly (downgrade) — not tested
- [x] `_compute_enrichment_state` still returns correct values for OCR+STT only (no caption)
- [x] Ingest without `scene_caption` still works (backward compat)
- [x] OpenSearch mapping update is additive (no existing field changes)
- [x] Search query boost hierarchy preserved (transcript > title > caption > OCR)
- [x] Embedding text construction unchanged (transcript + OCR only)
- [x] Internal caption upsert endpoint requires auth (`DRIVE_INTERNAL_API_KEY` + `X-Heimdex-Org-Id`)
- [x] Internal caption upsert is idempotent — verified with re-ingest on staging

### PR4 — Caption Worker (deployed to staging)
- [x] Worker starts with `SCENE_CAPTION_ENABLED=true` and polls — verified on staging
- [x] Model loaded once at startup (singleton) — "caption_engine_loaded_once" log confirmed
- [x] DB session factory created once (singleton) — code review confirmed
- [ ] pHash cache prevents duplicate captions — not implemented (design-only)
- [x] Worker only claims files with `keyframe_s3_prefix IS NOT NULL`
- [x] `FOR UPDATE SKIP LOCKED` prevents duplicate claims — code review confirmed
- [x] Failed caption sets status to "failed", doesn't crash worker — code review confirmed
- [x] Graceful shutdown on SIGTERM — signal handler registered

### PR5 — UI + Search (committed)
- [x] SceneCard renders caption when present — 2 new tests pass
- [x] SceneCard renders correctly when caption absent — conditional render verified
- [x] TypeScript compiles without errors
- [x] No new client-side API calls
- [x] Existing UI tests pass — 166/166 pass

---

## Staging Deployment Verification

| Check | Status | Notes |
|-------|--------|-------|
| Migration 014 applied | ✅ | `caption_status`, `caption_error` columns exist |
| OpenSearch `scene_caption` field | ✅ | korean_analyzer applied |
| API healthy | ✅ | `environment=staging`, `embedding_mode=real` |
| Caption worker running | ✅ | InternVL2-1B, ~15s/frame on CPU |
| First file e2e | ✅ | nævis MV (79 scenes): pending → running → done → re-ingested → searchable |
| Local placeholder captions | ✅ | 332 scenes with Korean placeholder |
| BM25 search on captions | ✅ | "초원 여성" finds scenes via caption content only |
| Search regression | ✅ | "라이브커머스" still returns 87 hits (no degradation) |
| Worker errors | ✅ | 0 failures after first file completed |

### Caption Progress (as of 2026-02-21)

| Status | Files | Scenes |
|--------|-------|--------|
| done | 1 | 79 |
| pending | 35 | 1,149 |
| failed | 0 | 0 |
| **Total** | **36** | **1,228** |

ETA for completion: ~4-5 hours at ~15s/frame on t3.xlarge CPU.

---

## Search Quality Impact

Captions add a new searchable surface for visual content not captured by transcript or OCR:

| Query | Before captioning | After captioning | Source |
|-------|-------------------|------------------|--------|
| "초원 여성" (meadow woman) | 0 hits | 5 hits | Caption-only matches from nævis MV |
| "초원 풍경" (meadow landscape) | 0 hits | 16 hits | Caption-only matches |
| "라이브커머스" | 87 hits | 87 hits | No regression (title/transcript matches unchanged) |

BM25 boost hierarchy: `transcript^2.0 > video_title.nori^1.5 > scene_caption^1.0 > ocr_text^0.6`
