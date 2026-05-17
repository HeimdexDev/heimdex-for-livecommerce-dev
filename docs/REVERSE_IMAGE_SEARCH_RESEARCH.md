# Reverse Image Search (Search BY Image) — Research Notes

**Date:** 2026-03-08
**Status:** Research complete, not planned for implementation. Preserved for future reference.

## Summary

Research into allowing users to upload an image and find visually similar video scenes. This was explored but is NOT the requested feature — the customer wants to search FOR images (visual merchandising assets from Google Drive), not search BY images. This document preserves the findings for potential future use.

## Key Finding: 70% Infrastructure Already Exists

Our existing SigLIP2 visual embedding pipeline, 3-way RRF fusion, and OpenSearch kNN index already support image-query search. The `visual_embedding` field (768-dim, HNSW, cosinesimil) accepts any 768-dim vector — whether from the text encoder or image encoder.

## Technical Approach

### What Exists (Reusable)
- SigLIP2 image encoder (`drive-visual-embed-worker/src/tasks/visual_embed.py`) — deployed on Aircloud+ GPU
- SigLIP2 text encoder (`api/app/modules/search/visual_embedding.py`) — running on API server (CPU, BF16)
- `visual_embedding` kNN field in OpenSearch v3 index — 768-dim, HNSW, cosinesimil, lucene engine
- `search_visual_vector()` in `scene_query.py` — accepts any 768-dim vector
- 3-way RRF fusion in `fusion.py` — handles BM25 + text kNN + visual kNN
- Scene result rendering in `SearchResults.tsx`

### What Would Need to Be Built
1. Load SigLIP2 vision encoder on API server (or HTTP endpoint on GPU worker)
2. `POST /api/search/scenes/by-image` FastAPI endpoint
3. Frontend: camera icon in search bar, drag-drop, paste handler
4. Image search API client (`searchByImage()`)
5. Multimodal query support (image + text simultaneously)

### Architecture Decision: Encode on API Server (CPU)
- SigLIP2 base-patch16-256 is ~350MB, latency ~150-400ms on CPU
- Acceptable for user-initiated search (same as text encoder latency)
- Scale-up path: HTTP endpoint on GPU worker (~10-15ms)

### UX Patterns (Industry Research)
- Entry point: camera icon in search bar (universal standard)
- Upload methods: file picker, drag-drop, Ctrl+V paste
- Results: same scene card grid (identical SceneSearchResponse)
- No similarity slider (industry consensus: users don't understand numeric scores)
- "Find similar" button on result cards for iterative refinement
- Multimodal: image sets visual anchor, text refines intent

### Implementation Estimate
- Phase 0-4: ~7-10 days
- Phase 5 (crop-to-search): separate sprint

## References
- SigLIP2 shared embedding space: image encoder and text encoder produce vectors in the same 768-dim L2-normalized space
- Image-to-image is better aligned than text-to-image (no cross-modal gap)
- Preprocessing: `AutoImageProcessor` handles RGB conversion, resize, rescale, normalize
- OpenSearch kNN query is identical for image vectors and text vectors
- Reference implementation: `navneet83/multimodal-mountain-peak-search`
