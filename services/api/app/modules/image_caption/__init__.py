"""Image caption module.

Generates VMD-style captions for content_type=image scene rows by calling
OpenAI's gpt-4o Vision API. Runs **inside the api container** as an async
background task, not as a separate worker. See README.md for why.

Two entry points:
  - Realtime: hook in ingest/internal_router.py schedules a background
    task after an image scene is indexed, via asyncio.create_task.
  - Backfill: app/cli/backfill_image_caption_batch.py uses OpenAI's
    Batch API for cost-efficient bulk captioning of existing images.

Both paths write captions through the existing /internal/ingest/enrich
path, which already enforces scene_overrides.protected — user-edited
captions are never overwritten.
"""
