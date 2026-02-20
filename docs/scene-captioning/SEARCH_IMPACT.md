# Phase E — Search & Indexing Impact

**Date:** 2026-02-20
**Status:** Complete
**Purpose:** Decide how scene captions integrate with search. BM25, vector, or display-only?

---

## Decision: BM25-Searchable, No Additional Embedding

### Rationale

| Option | Pros | Cons | Decision |
|--------|------|------|----------|
| **A: BM25 only** | Zero additional embedding cost, works with korean_analyzer, instant | No semantic search on captions | **Selected** |
| B: BM25 + embed captions | Semantic search on visual descriptions | Violates constraint: "do not increase per-scene embedding calls" | Rejected |
| C: Fold into existing embedding text | Captions influence vector similarity | Changes embedding behavior for ALL existing scenes on re-ingest; caption quality varies | Rejected |
| D: Display only | Simplest, no search impact | Wasted data — captions contain searchable keywords | Rejected |

**Key constraint:** "Do not increase per-scene embedding calls." This rules out options B and C. Captions are BM25-indexed using the existing `korean_analyzer` (Nori tokenizer), which already handles Korean text well.

**Future upgrade path:** If caption quality proves high and users search for visual concepts ("빨간 원피스", "삼성 갤럭시 시연"), we can fold `scene_caption_norm` into the embedding text in a future PR. This is a one-line change in `ingest/service.py`:

```python
# Current (v1): embed transcript + OCR only
embedding_text = f"{transcript_norm} {ocr_norm}".strip()

# Future (v2): embed transcript + OCR + caption
embedding_text = f"{transcript_norm} {ocr_norm} {caption_norm}".strip()
```

---

## OpenSearch Mapping Changes

### New Fields

```python
# In scene_client.py, add to SCENE_MAPPING["properties"]
"scene_caption": {
    "type": "text",
    "analyzer": "korean_analyzer",    # Nori tokenizer for Korean BM25
},
"scene_caption_raw": {
    "type": "text",
    "analyzer": "standard",           # Fallback for non-Korean content
},
```

**Adding new fields is zero-downtime.** OpenSearch `PUT /_mapping` allows adding fields without reindex. Existing documents get `null` for new fields — they simply don't match caption queries until re-ingested.

```
PUT /heimdex_scenes_v1/_mapping
{
  "properties": {
    "scene_caption": { "type": "text", "analyzer": "korean_analyzer" },
    "scene_caption_raw": { "type": "text", "analyzer": "standard" }
  }
}
```

### No Index Rebuild Required

- Existing 1,560 scenes continue working unchanged
- New/re-ingested scenes include `scene_caption` field
- Progressive rollout: as videos are re-captioned, search quality improves gradually

---

## Search Query Changes

### Current Multi-Match Query

```python
# scene_service.py — current BM25 query
"should": [
    {"match": {"transcript_norm": {"query": q, "boost": 2.0}}},
    {"match": {"video_title.nori": {"query": q, "boost": 1.5}}},
    {"match": {"ocr_text_norm": {"query": q, "boost": 0.6}}},
]
```

### Updated Query (with caption)

```python
"should": [
    {"match": {"transcript_norm": {"query": q, "boost": 2.0}}},     # Spoken words — highest signal
    {"match": {"video_title.nori": {"query": q, "boost": 1.5}}},    # Human-written title
    {"match": {"scene_caption": {"query": q, "boost": 1.0}}},       # NEW — visual description
    {"match": {"ocr_text_norm": {"query": q, "boost": 0.6}}},       # On-screen text
]
```

### Boost Hierarchy Rationale

| Field | Boost | Rationale |
|-------|-------|-----------|
| `transcript_norm` | 2.0 | Ground truth — what was actually said |
| `video_title.nori` | 1.5 | Human-curated, high intent signal |
| **`scene_caption`** | **1.0** | **Generated text — useful but less reliable than human input** |
| `ocr_text_norm` | 0.6 | Noisy — includes watermarks, UI elements |

Caption boost = 1.0 (neutral) because:
- Higher than OCR (captions describe the scene holistically, OCR is fragmentary)
- Lower than title (captions are model-generated, titles are human-written)
- Equal to base relevance — we let term frequency and doc frequency do the ranking

---

## Search Quality Impact Analysis

### Queries That Benefit From Captions

Captions help when **the visual content isn't captured by transcript or OCR**:

| Query | Current Result | With Captions |
|-------|---------------|---------------|
| "빨간 원피스" (red dress) | Miss if not mentioned verbally | Hit if caption says "진행자가 빨간 원피스를 들고 있다" |
| "삼성 갤럭시" (Samsung Galaxy) | Hit via OCR (product label) | Also hit via caption (product demo description) |
| "주방" (kitchen) | Miss unless mentioned | Hit if caption describes kitchen setting |
| "화장품 시연" (cosmetics demo) | Hit via transcript if said | Stronger match with visual confirmation |

### Queries That Don't Change

| Query | Why No Change |
|-------|---------------|
| "1+1 세일" (buy-one-get-one sale) | Captured by OCR and transcript — caption adds no new info |
| "무료배송" (free shipping) | Text-based concept, not visual |
| "진행자 이름" (host name) | Caption doesn't know the host's name |

### Expected Impact

- **New recall:** 10-20% more scenes discoverable for visual-concept queries
- **No precision loss:** Caption boost is conservative (1.0); won't override strong transcript matches
- **Gradual improvement:** Only re-ingested scenes benefit; existing scenes unaffected

---

## Ingest Pipeline Changes

### `SceneIngestService.ingest_scenes()` — Additions

```python
# After existing ocr normalization (step 3)
caption_norm = normalize_transcript(scene.scene_caption) if scene.scene_caption else ""

# In document builder
doc["scene_caption"] = scene.scene_caption or ""
doc["scene_caption_raw"] = scene.scene_caption or ""

# Embedding text stays UNCHANGED (v1)
embedding_text = f"{transcript_norm} {ocr_norm}".strip()
# NOT: f"{transcript_norm} {ocr_norm} {caption_norm}".strip()  ← v2 upgrade path
```

### Backward Compatibility

- `scene_caption` is `Optional[str]` in `IngestSceneDocument`
- Existing ingest payloads without this field → `scene_caption = None` → stored as empty string
- Existing search queries work unchanged (new `should` clause simply doesn't match null fields)

---

## API Response Changes

### `SceneResult` Schema

```python
# search/schemas.py
class SceneResult(BaseModel):
    # ... existing fields
    scene_caption: Optional[str] = None  # NEW
```

### Response Example

```json
{
  "scene_id": "video123_scene_5",
  "video_title": "여름 원피스 특가 라이브",
  "transcript_norm": "이 원피스가 정말 예쁘죠? 색상이 다섯 가지나 있어요.",
  "ocr_text_norm": "SUMMER SALE 49,900원",
  "scene_caption": "진행자가 카메라 앞에서 플로럴 패턴의 여름 원피스를 들고 색상 옵션을 보여주고 있다.",
  "start_ms": 45000,
  "end_ms": 52000
}
```

---

## Measurement Plan

### A/B Test Design (Post-Implementation)

1. **Baseline:** Run existing 15 golden queries on staging (current hit rates)
2. **Caption ingest:** Re-ingest all 15 videos with captions enabled
3. **Re-test:** Run same 15 queries + 10 new "visual concept" queries
4. **Compare:** Hit@10, MRR, rank position

### New Golden Queries (Visual Concepts)

| ID | Query | Expected Scene | Why Caption Helps |
|----|-------|---------------|-------------------|
| V01 | "빨간 립스틱" | Beauty demo scene | Visual product not in transcript |
| V02 | "주방에서 요리" | Cooking scene | Setting description |
| V03 | "제품 클로즈업" | Product zoom scene | Camera angle description |
| V04 | "박스 언박싱" | Unboxing scene | Action description |
| V05 | "흰색 배경" | Studio scene | Background description |

---

## Summary

| Aspect | Decision |
|--------|----------|
| Search integration | BM25 only (no embedding) |
| Analyzer | `korean_analyzer` (Nori) — same as transcript |
| Boost weight | 1.0 (between title 1.5 and OCR 0.6) |
| Embedding text | Unchanged (transcript + OCR only) |
| Index migration | `PUT /_mapping` — zero downtime |
| Backward compatible | Yes — new field is Optional, null → no match |
| Future upgrade | Fold into embedding text (one-line change) |
