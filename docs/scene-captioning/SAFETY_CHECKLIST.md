# Scene Captioning — Safety Checklist

**Created:** 2026-02-20
**Updated as PRs land.**

---

## Kill Switch

| Variable | Default | Effect when `false` |
|----------|---------|---------------------|
| `SCENE_CAPTION_ENABLED` | `false` | Caption worker does nothing; SaaS behavior 100% unchanged |

---

## Regression Surfaces

| Surface | Risk | Verification | PR1 | PR2 | PR3 | PR4 | PR5 |
|---------|------|-------------|-----|-----|-----|-----|-----|
| **Agent ingest** | New optional field ignored by old agents | `pytest` contracts; ingest without `scene_caption` | | | | | |
| **Drive sync** | DriveFile model change could break queries | Alembic migration + existing drive tests | — | — | | | — |
| **OCR enrichment** | State machine change could break OCR status | `_compute_enrichment_state` tests | — | — | | | — |
| **STT enrichment** | State machine change could break STT status | `_compute_enrichment_state` tests | — | — | | | — |
| **Search (BM25)** | New field in multi-match could degrade results | Existing search tests + manual golden queries | — | — | | — | |
| **Search (vector)** | Embedding text must NOT change | Verify `embedding_text` construction unchanged | — | — | | — | — |
| **Thumbnails** | Keyframe S3 keys must not change | Verify `enrichment_keyframe_s3_key` unchanged | — | — | — | | — |
| **Exports** | Export schemas must still serialize | contracts export tests | | — | — | — | — |
| **Multi-org tenancy** | Caption worker must scope by org_id | claim query includes org filter; internal endpoint requires X-Heimdex-Org-Id | — | — | | | — |
| **Multi-device** | Device registration unaffected | No device model changes | — | — | — | — | — |
| **UI rendering** | SceneCard must not break for scenes without captions | Conditional render `{result.scene_caption && ...}` | — | — | — | — | |

Legend: ✅ = verified, ⬜ = pending, — = not applicable to this PR

---

## Per-PR Verification

### PR1 — Contracts
- [ ] `pytest` in heimdex-media-contracts passes (all existing + new tests)
- [ ] `IngestSceneDocument` without `scene_caption` still parses (backward compat)
- [ ] `IngestSceneDocument` with `scene_caption` parses correctly
- [ ] `SceneDocument` without `scene_caption` still parses (backward compat)
- [ ] `pip install -e .` succeeds

### PR2 — Pipelines
- [ ] `pytest` in heimdex-media-pipelines passes (all existing + new tests)
- [ ] `pip install -e .` succeeds (no vision deps required for base install)
- [ ] `pip install -e ".[vision]"` installs vision dependencies
- [ ] `CaptionEngine` protocol matches `OCREngine` pattern
- [ ] Mock-based tests don't require HF model download

### PR3 — SaaS Backend
- [ ] `pytest` in dev-heimdex-for-livecommerce passes (all existing + new tests)
- [ ] Alembic migration runs forward cleanly
- [ ] Alembic migration runs backward cleanly (downgrade)
- [ ] `_compute_enrichment_state` still returns correct values for OCR+STT only (no caption)
- [ ] Ingest without `scene_caption` still works (backward compat)
- [ ] OpenSearch mapping update is additive (no existing field changes)
- [ ] Search query boost hierarchy preserved (transcript > title > caption > OCR)
- [ ] Embedding text construction unchanged (transcript + OCR only)
- [ ] Internal caption upsert endpoint requires auth
- [ ] Internal caption upsert is idempotent

### PR4 — Caption Worker
- [ ] Worker starts with `SCENE_CAPTION_ENABLED=false` and does nothing
- [ ] Worker starts with `SCENE_CAPTION_ENABLED=true` and polls
- [ ] Model loaded once at startup (singleton)
- [ ] DB session factory created once (singleton)
- [ ] S3 client created once (singleton)
- [ ] pHash cache prevents duplicate captions
- [ ] Worker only claims files where OCR+STT are done
- [ ] `FOR UPDATE SKIP LOCKED` prevents duplicate claims
- [ ] Failed caption sets status to "error", doesn't crash worker
- [ ] Graceful shutdown on SIGTERM

### PR5 — UI + Search
- [ ] SceneCard renders caption when present
- [ ] SceneCard renders correctly when caption absent
- [ ] TypeScript compiles without errors
- [ ] No new client-side API calls
- [ ] Existing UI tests pass
