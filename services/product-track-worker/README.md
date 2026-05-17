# product-track-worker

Aircloud GPU worker for the second stage of the shorts-auto product
mode v2 pipeline. Consumes `product.track_job` messages from
`heimdex-product-track-queue`, runs SigLIP2 retrieval + SAM2 mask
propagation + window assembly + alignment + subset selection, and
posts the resulting stitching plan back to the api via
`/internal/products/{job_id}/complete`.

## Phase 3c-A scaffold (current state)

This directory contains the **scaffold** for the track worker:

- ✅ `settings.py` — env config + tracking thresholds
- ✅ `api_client.py` — bearer-authed HTTP client for callbacks +
  Phase 3b read endpoints
- ✅ `worker.py` — boot loop + ConsumerLoop
- ✅ `dispatcher.py` — message routing + last-ditch fail callback
- ✅ `siglip2_clients.py` — concrete SigLIP2 embedder /
  CoarseRetrievalClient / KeyframeFetcher
- ✅ `openai_picker.py` — gpt-4o-mini SubsetPicker (with
  GreedyPicker fallback)
- ⚠️ `sam2_loader.py` — **stub** (raises `NotImplementedError`)
- ⚠️ `sam2_tracker.py` — **stub** (raises `NotImplementedError`)
- ✅ `tasks/track.py` — orchestration
- ✅ Tests for api_client + dispatcher

## Phase 3c-B follow-up (next PR)

What ships next to make this worker production-ready:

1. **Real SAM2 integration**: pick the python package (Meta's
   official `sam2`, HF transformers' `Sam2Model`, or ultralytics),
   implement `sam2_loader.load_sam2` + `Sam2TrackerImpl.track`.
   Calibrate the variant on staging goldens (≥0.6 mean window IoU
   floor per plan §6.2 calibration gate).
2. **Catalog entry fetch endpoint**: the api needs
   `GET /internal/products/catalog/{catalog_entry_id}` returning
   `{canonical_crop_s3_key, bbox_xywh, llm_label}`. Currently
   `tasks/track.py::_fetch_canonical_crop` raises
   `NotImplementedError` until this endpoint lands.
3. **Render enqueue**: the worker should call `/api/shorts/render`
   internally with a CompositionSpec built from the stitch plan.
   3c-A's `complete_track` accepts `render_job_id=None` so the
   worker can ship without this and surface "tracked, render
   pending" in the UI.
4. **Integration tests**: end-to-end happy path with all real model
   calls mocked at the Protocol boundary.

## Operating notes

- **Refuse-to-start guards**: worker boots only when
  `AUTO_SHORTS_PRODUCT_V2_ENABLED=true` AND a CUDA GPU is available
  (override with `TRACK_ALLOW_CPU=true` for local dev only —
  SAM2-on-CPU is not viable for prod).
- **SigLIP2 variant pin**: `google/siglip2-base-patch16-256`.
  MUST match drive-visual-embed-worker exactly — the OS coarse
  pre-filter at `/internal/videos/{file_id}/scenes-by-visual-similarity`
  compares the worker's embedding against scene-level vectors stored
  by drive-visual-embed-worker. Drift breaks ranking silently.
- **Cost cap**: `AUTO_SHORTS_PRODUCT_V2_DAILY_BUDGET_USD=50` (api
  side). Each track job is roughly $0.50 for SAM2 GPU minutes +
  ~$0.005 LLM picker; budget = ~100 track jobs/day at the cap.
- **Lease**: 1800s (30 min). Matches the queue's visibility timeout.
  A worker that crashes mid-track loses the lease at 30min and the
  message becomes available for re-claim.

## Build

```bash
# from workspace root (sibling layout: dev-heimdex-for-livecommerce
# + heimdex-media-contracts + heimdex-media-pipelines)
docker build \
  -f dev-heimdex-for-livecommerce/services/product-track-worker/Dockerfile.gpu \
  -t heimdex-product-track-worker:gpu \
  .
```

## Tests

```bash
cd services/product-track-worker
pytest tests/ -v
```

Lib-level pure-function tests live in `heimdex-media-pipelines`
(`tests/product_track/`) — the worker's tests cover only the
plumbing (api_client + dispatcher).

## Deploy

Same pattern as product-enumerate-worker:

1. CI build via `.github/workflows/build-gpu-images.yml` →
   pushes to GHCR.
2. Provision Aircloud container from the GHCR image; capture UUID →
   `AIRCLOUD_ENDPOINT_PRODUCT_TRACK` on the staging EC2 `.env`.
3. (IAM ARN already added in Phase 2.5c — same SQS
   policy covers track + enumerate.)

## Environment variables

See `src/settings.py` for the full list. Minimum to run on Aircloud:

```
ENVIRONMENT=staging
LOG_LEVEL=INFO
SQS_CONSUMER_ENABLED=true
SQS_REGION=ap-northeast-2
S3_REGION=ap-northeast-2
DRIVE_S3_BUCKET=heimdex-drive-staging
AWS_DEFAULT_REGION=ap-northeast-2
AWS_ACCESS_KEY_ID=<heimdex-aircloud-worker key>
AWS_SECRET_ACCESS_KEY=<heimdex-aircloud-worker secret>
DRIVE_API_BASE_URL=https://devorg.app.heimdexdemo.dev
DRIVE_INTERNAL_API_KEY=<same as drive-blur-worker / drive-stt-worker>
SQS_PRODUCT_TRACK_QUEUE_URL=https://sqs.ap-northeast-2.amazonaws.com/752198711321/heimdex-product-track-queue
OPENAI_API_KEY=<same as image-caption / shorts-auto-llm>
PRODUCT_V2_ENABLED=true
USE_GPU=true
```

Optional (F1 Phase 3 — per-service identity):

```
INTERNAL_SERVICE_ID=product-track-worker
```

When set, the worker sends `X-Heimdex-Service-Id` + the per-service
token (which must be in the api's `INTERNAL_SERVICE_TOKENS` env). Omit
to use the legacy global bearer (still accepted by the api during the
F1 Phase 3 backward-compat window).
