# product-enumerate-worker

Phase 2 worker for the **shorts-auto product mode v2** lazy pipeline.
Consumes ``product.enumerate_job`` messages from the
``heimdex-product-enumerate-queue`` SQS queue, runs LLM-vision
enumeration over the video's keyframes, deduplicates with SigLIP2
clustering, and POSTs the resulting catalog entries back to the API
via ``/internal/products/{job_id}/complete``.

Plan: [`.claude/plans/shorts-auto-product-v2.md`](../../.claude/plans/shorts-auto-product-v2.md)

## Models

| Component | Pinned variant | Why |
|---|---|---|
| Vision LLM | ``gpt-4o-mini`` | Cost decision §15 — locked vs gpt-4o pending staging-goldens precision floor (≥0.80). Fall-back path documented in §14. |
| Embedding | ``google/siglip2-base-patch16-256`` (768-dim) | Must match ``drive-visual-embed-worker`` exactly so OS scene-level vectors stay reusable as the coarse pre-filter for Phase 3 tracking. |

## Required env (see ``src/settings.py``)

| Var | Notes |
|---|---|
| ``PRODUCT_V2_ENABLED`` | Worker hard-refuses to boot when false |
| ``SQS_PRODUCT_ENUMERATE_QUEUE_URL`` | Provisioned 2026-04-29 |
| ``OPENAI_API_KEY`` | Required at boot |
| ``DRIVE_API_BASE_URL`` + ``DRIVE_INTERNAL_API_KEY`` | For ``/internal/products/*`` callbacks |
| ``ENUMERATE_ALLOW_CPU`` | Default false; SigLIP2 on CPU is workable for dev/test only |
| ``ENUMERATION_VERSION`` / ``ENUMERATION_PROMPT_VERSION`` | Mirror ``heimdex_media_contracts.product.EnumerationPrompt.VERSION`` |

## Boot

```bash
docker build -f services/product-enumerate-worker/Dockerfile.gpu \
             -t heimdex-product-enumerate-worker:gpu .
docker run --gpus all --env-file .env heimdex-product-enumerate-worker:gpu
```

Or via compose with the ``product-enum`` profile:

```bash
docker compose --profile product-enum up product-enumerate-worker
```

## Phase 2 status (scaffolding only)

The pipeline scaffolding is wired end-to-end **except** for the two
I/O placeholders in ``src/tasks/enumerate.py`` marked
``[PHASE-2-IO]``:

1. ``_fetch_keyframes`` — needs a new internal API endpoint
   ``GET /internal/videos/{video_id}/scenes-with-keyframes`` that
   returns ``[(scene_id, frame_idx, keyframe_s3_key), ...]``. Both the
   enumerate and (Phase 3) track workers will consume this.
2. ``_upload_crops_and_build_payload`` — worker-side S3 client +
   payload assembly for the API ``complete`` callback.

Until those land, the worker boots cleanly but every job short-
circuits to ``video_not_found``. That's the right placeholder
behavior — the API surfaces a deterministic error in the gallery
empty state so we can finish the IO wiring without breaking the
in-flight UX assumptions.

## Loose-coupling boundaries

- **No imports from ``app.modules.*``.** Worker shares only contracts
  and pipelines with the API. Verified by grep.
- **VLM client is behind a Protocol** (``heimdex_media_pipelines.product_enum.vlm_client.VlmClient``)
  so unit tests can inject a stub without an OpenAI key.
- **SigLIP2 lives in pipelines** (``heimdex_media_pipelines.siglip2``),
  not in the worker, so the Phase 3 track worker can reuse the same
  shared loader without duplicating model code.
