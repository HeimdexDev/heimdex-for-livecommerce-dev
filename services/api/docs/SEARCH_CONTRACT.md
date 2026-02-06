# Heimdex Search Quality Contract

This document defines the search quality contract for the Heimdex hybrid search system.
All search behavior must conform to these specifications, and tests must enforce them.

## 1. Candidate Generation

### Lexical Search (BM25)
- **Index field**: `transcript_norm` (analyzed with Nori or fallback analyzer)
- **Candidate pool size**: `SEARCH_LEXICAL_TOP_K` (default: 200)
- **Query features**:
  - Short queries (≤3 words): Phrase boost of 2.0x with slop=1
  - All queries: Minimum 50% term match required
  - Operator: OR (any matching terms contribute)

### Vector Search (kNN)
- **Embedding model**: `intfloat/multilingual-e5-large` (1024 dimensions)
- **Query prefix**: `"query: "` + query text (E5 requirement)
- **Candidate pool size**: `SEARCH_VECTOR_TOP_K` (default: 200)
- **Similarity metric**: Cosine similarity via HNSW
- **HNSW parameters**: ef_construction=128, m=24, ef_search=100

### Filter Application
Filters are applied BEFORE candidate retrieval (pre-filtering):
- `org_id`: Always required, applied in both lexical and vector queries
- `date_from/date_to`: Range filter on `capture_time`
- `source_types`: Terms filter on `source_type`
- `library_ids`: Terms filter on `library_id`
- `person_cluster_ids`: Terms filter on `people_cluster_ids`

## 2. Fusion (Reciprocal Rank Fusion)

### RRF Formula
```
rrf_score(rank, k) = 1 / (k + rank)
```

Where:
- `rank`: 1-indexed position in candidate list
- `k`: RRF constant (default: 60, configurable via `SEARCH_RRF_K`)
- Items not in a result set have `rank = None` → `rrf_score = 0`

### Weighted Fusion
```
lexical_contribution = (1 - alpha) × rrf_score(lexical_rank, k)
vector_contribution = alpha × rrf_score(vector_rank, k)
fused_score = lexical_contribution + vector_contribution
```

### Alpha Parameter
| Value | Mode | Behavior |
|-------|------|----------|
| 0.0 | Exact | Pure lexical (BM25 keyword matching) |
| 0.5 | Balanced | Equal weight to both signals |
| 1.0 | Meaning | Pure semantic (vector similarity) |

**Constraints**: `0.0 ≤ alpha ≤ 1.0` (validated in API schema)

**Boost behavior**: Items appearing in BOTH result sets receive contributions from both, resulting in higher scores than items in only one set.

## 3. Quality Factor

Applied after fusion to penalize low-quality transcripts.

### Thresholds
- `MIN_TRANSCRIPT_CHARS`: 20 (below this: minimum quality)
- `GOOD_TRANSCRIPT_CHARS`: 100 (above this: full quality)
- `QUALITY_FLOOR`: 0.7 (minimum multiplier, never filters completely)

### Calculation
```python
if char_count >= 100:
    quality_factor = 1.0
elif char_count <= 20:
    quality_factor = 0.7
else:
    # Linear interpolation
    ratio = (char_count - 20) / 80
    quality_factor = 0.7 + ratio * 0.3
```

### Character Count Source
Fallback chain (in order):
1. `transcript_char_count_normalized` (pre-computed)
2. `transcript_char_count` (legacy raw count)
3. Computed via `get_normalized_char_count(transcript_raw)`

### Adjusted Score
```
adjusted_score = fused_score × quality_factor
```

## 4. Diversification

Prevents a single video from dominating results.

### Parameters
- `max_per_video`: Maximum scenes per video (default: 4)
- `target_count`: Target result count (default: 20)

### Algorithm
1. Sort candidates by `adjusted_score` descending
2. First pass: Include items respecting per-video limit
3. Second pass: Fill remaining slots with penalized items
4. Mark overflow items with `diversification_penalty = True`

### Effective Max Calculation
Dynamic adjustment based on result distribution:
```python
if total_candidates <= target_count:
    effective_max = total_candidates  # No capping needed
elif unique_videos == 1:
    effective_max = target_count  # Single video, return all
elif unique_videos < target_count // max_per_video:
    effective_max = max(max_per_video, target_count // unique_videos)
else:
    effective_max = max_per_video  # Standard cap
```

## 5. Observability (Debug Fields)

All fields returned in `DebugInfo` for each result:

| Field | Type | Description |
|-------|------|-------------|
| `lexical_rank` | int\|null | Position in BM25 results (1-indexed) |
| `lexical_score` | float\|null | Raw BM25 score from OpenSearch |
| `vector_rank` | int\|null | Position in kNN results (1-indexed) |
| `vector_score` | float\|null | Cosine similarity score |
| `lexical_contribution` | float | RRF contribution from lexical |
| `vector_contribution` | float | RRF contribution from vector |
| `fused_score` | float | Combined RRF score |
| `quality_factor` | float | Transcript quality multiplier (0.7-1.0) |
| `adjusted_score` | float | Final ranking score |
| `diversification_penalty` | bool | True if added after per-video limit |

### Response Metadata
- `total_candidates`: Count before diversification
- `query`: Original search query
- `alpha`: Fusion parameter used

## 6. Invariants (Test Assertions)

### Ranking Invariants
1. Results are sorted by `adjusted_score` descending
2. `adjusted_score = fused_score × quality_factor`
3. `fused_score = lexical_contribution + vector_contribution`
4. `0.7 ≤ quality_factor ≤ 1.0`
5. `0.0 ≤ alpha ≤ 1.0`

### Alpha Invariants
1. `alpha = 0.0` → `vector_contribution = 0` for all items
2. `alpha = 1.0` → `lexical_contribution = 0` for all items
3. `alpha = 0.5` → contributions approximately equal (same rank)

### Diversification Invariants
1. `len(results) ≤ target_count`
2. Items with `diversification_penalty = True` appear after non-penalized items from same video
3. If sufficient video diversity exists, no video has more than `max_per_video` results

### Quality Invariants
1. `char_count >= 100` → `quality_factor = 1.0`
2. `char_count <= 20` → `quality_factor = 0.7`
3. `20 < char_count < 100` → `0.7 < quality_factor < 1.0`

## 7. Configuration Reference

| Parameter | Default | Env Var | Description |
|-----------|---------|---------|-------------|
| `search_lexical_top_k` | 200 | `SEARCH_LEXICAL_TOP_K` | Lexical candidate pool |
| `search_vector_top_k` | 200 | `SEARCH_VECTOR_TOP_K` | Vector candidate pool |
| `search_rrf_k` | 60 | `SEARCH_RRF_K` | RRF ranking constant |
| `search_max_scenes_per_video` | 4 | `SEARCH_MAX_SCENES_PER_VIDEO` | Diversification cap |
| `search_page_size` | 20 | `SEARCH_PAGE_SIZE` | Result count |
| `embedding_model` | multilingual-e5-large | `EMBEDDING_MODEL` | Embedding model |
| `embedding_dimension` | 1024 | `EMBEDDING_DIMENSION` | Vector dimension |
