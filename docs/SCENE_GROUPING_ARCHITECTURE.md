# Scene Grouping Architecture

## Overview

Semantic scene grouping is a **toggle feature** on the video detail page that groups consecutive, semantically-related scenes into collapsible clusters. It uses text embeddings (1024-dim, `intfloat/multilingual-e5-large`) and visual embeddings (768-dim, `google/siglip2-base-patch16-256`) to compute pairwise similarity between adjacent scenes, then places group boundaries where similarity drops below a threshold.

**Key properties:**
- Computed on-the-fly (no new storage, no new workers, no OpenSearch schema changes)
- Zero coupling — standalone `modules/grouping/` module imports only `SceneSearchClient`
- No labels — pure boundary detection + visual grouping
- Lazy-loaded — groups only fetched when the user toggles the feature on

## Architecture

```
┌──────────────┐     GET /api/videos/{id}/scene-groups?threshold=0.55
│   Frontend    │────────────────────────────────────────────────────►
│  ScenesPanel  │◄────────────────────────────────────────────────────
│  + toggle     │     SceneGroupsResponse { groups: SceneGroup[] }
└──────────────┘

┌──────────────┐     ┌──────────────────┐     ┌───────────────────┐
│   router.py   │────►│   service.py      │────►│  scene_facets.py  │
│  (endpoint)   │     │  (orchestrator)   │     │  (OpenSearch)     │
└──────────────┘     └──────┬───────────┘     └───────────────────┘
                            │
                     ┌──────▼───────────┐
                     │  algorithm.py     │
                     │  (pure functions) │
                     └──────────────────┘
```

## Backend Module: `modules/grouping/`

### Files

| File | Purpose | Dependencies |
|------|---------|--------------|
| `algorithm.py` | Pure functions: `_dot_product`, `compute_pairwise_similarity`, `find_group_boundaries`, `_merge_small_groups` | None (stdlib only) |
| `schemas.py` | `SceneGroup`, `SceneGroupsResponse` Pydantic models | `VideoScene` from `videos/schemas.py` |
| `service.py` | `GroupingService` — fetches scenes, runs algorithm, builds response | `SceneSearchClient` |
| `router.py` | `GET /api/videos/{video_id}/scene-groups` | `GroupingService` via DI |

### Algorithm Design

**`compute_pairwise_similarity(scenes)`**
- For N scenes, returns N-1 similarity scores
- Adaptive signal fusion:
  - Both text + visual → weighted average (default: text=0.6, visual=0.4)
  - Single signal → uses it alone (weight=1.0)
  - No embeddings → 0.5 (neutral, avoids false boundaries)
- For L2-normalized vectors: `cosine_similarity == dot_product`
- Output clamped to [0.0, 1.0]

**`find_group_boundaries(similarities, total_scenes, threshold=0.55)`**
- Boundary placed where `similarity < threshold`
- `_merge_small_groups()` absorbs undersized groups into neighbors with higher connecting similarity
- Coverage invariant: all scenes covered, no gaps, `groups[0].start == 0`, `groups[-1].end == total_scenes - 1`

### OpenSearch Query

`scene_facets.py:get_video_scenes_with_embeddings()` paginates all scenes (200/page) with both embedding fields in `_source`. Standard `bool.filter` on `org_id` + `video_id`, sorted by `start_ms asc`.

### API

```
GET /api/videos/{video_id}/scene-groups?threshold=0.55
Authorization: Bearer <token>

Response:
{
  "video_id": "...",
  "total_groups": 4,
  "total_scenes": 25,
  "groups": [
    {
      "group_index": 0,
      "start_ms": 0,
      "end_ms": 60000,
      "scene_count": 6,
      "representative_scene_id": "..._scene_3",
      "scenes": [/* VideoScene objects, no embedding vectors */]
    }
  ]
}
```

## Frontend

### Files

| File | Purpose |
|------|---------|
| `types/videos.ts` | `SceneGroup`, `SceneGroupsResponse` interfaces |
| `api/videos.ts` | `getVideoSceneGroups()` API client |
| `hooks/useSceneGroups.ts` | `useSceneGroups()` — lazy fetch + state management |
| `components/SceneGroupCard.tsx` | Collapsible group card (header + expanded SceneCards) |
| `components/VideoDetailPage.tsx` | ScenesPanel: toggle button + conditional rendering |

### UX Behavior

1. Toggle button ("의미 그룹") appears when `≥ 5 scenes` and no active search
2. First toggle-on triggers lazy `GET /scene-groups` fetch
3. Grouped view shows `SceneGroupCard` components (no pagination)
4. Click group header → expands to show individual `SceneCard` components
5. Search overrides grouping (automatically switches to flat view)
6. Toggle off → returns to standard paginated flat view

### SceneGroupCard

- **Collapsed**: Representative thumbnail (middle scene) + time range + scene count badge + chevron
- **Expanded**: Renders existing `SceneCard` components (reused, not duplicated)
- Zero new dependencies

## Test Coverage

| Test File | Tests | Scope |
|-----------|-------|-------|
| `test_grouping_algorithm.py` | 41 | `_dot_product`, `compute_pairwise_similarity`, `find_group_boundaries`, `_merge_small_groups`, integration |
| `test_grouping_router.py` | 15 | `_strip_embeddings`, `GroupingService`, schema validation |
| `SceneGroupCard.test.tsx` | 5 | Collapsed/expanded rendering, toggle, scene count |
| **Total** | **61** | |

## Configuration

| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| `threshold` | 0.55 | 0.0–1.0 | Similarity below this creates a boundary. Lower = fewer groups, higher = more groups. |
| `text_weight` | 0.6 | — | Relative weight for text embedding similarity (hardcoded) |
| `visual_weight` | 0.4 | — | Relative weight for visual embedding similarity (hardcoded) |
| `min_group_size` | 2 | — | Groups smaller than this are merged into neighbors (hardcoded) |

## Coupling Analysis

The grouping module has **zero coupling** to the rest of the system:

- **Imports**: `SceneSearchClient` (read-only OpenSearch queries) + `VideoScene` (Pydantic model)
- **No schema changes**: No new OpenSearch fields, no migrations, no new workers
- **No side effects**: Algorithm module is pure functions (no I/O)
- **Removable**: Delete `modules/grouping/`, remove 2 lines from `main.py`/`dependencies.py`, revert `SceneCard` export → feature fully removed
