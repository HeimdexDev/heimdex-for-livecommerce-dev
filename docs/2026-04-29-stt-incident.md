# 2026-04-29 — STT data missing on new staging livecommerce uploads

## Symptom

Newly uploaded videos on staging (`devorg.app.heimdexdemo.dev`) showed visual
scene captions but no transcript / STT data. Two distinct populations were
affected; both presented the same way to the user but had different root
causes.

## Affected files (snapshot at investigation time)

* **8 videos** updated 2026-04-28 05:12-05:14 UTC: `processing_status=indexed`,
  `stt_status=failed`, `stt_result_s3_key=NULL`, `caption_status=NULL` in PG.
  OpenSearch scene docs had `scene_caption` populated (Korean visual
  descriptions) but `transcript_raw=''` for every scene. Filenames
  `ppl_youtube_*.mp4`, `carcrash_korea.mp4`, `260324_닥스 헤지스 골프.mp4`.
* **155 dashcam-style videos** uploaded 04-15..04-16 stuck at
  `processing_status in ('pending','failed')`, `scene_count=0`,
  `audio_s3_key=NULL`. Filenames `bb_1_*_vehicle_*.mp4`, `bb_3_*.mp4`,
  `carcrash_*.mp4`. 16+ `transcode_failed` events in `worker_events` from
  2026-04-28 05:09-05:14, all `ffmpeg ... -vn -acodec pcm_s16le ...`
  exit 234.

## Root cause #1 — `asyncio.create_task` on a `Future`

**File:** `services/api/app/modules/drive/internal_router.py:319-330` (pre-fix).

The deferred-caption block in `update_job_status` did

```python
asyncio.create_task(
    asyncio.get_running_loop().run_in_executor(
        None, lambda: publish_scene_enrichment_jobs(...),
    )
)
```

`run_in_executor` returns an `asyncio.Future` (wrapped via `_chain_future`),
not a coroutine. `create_task` requires a coroutine and raises

```
TypeError: a coroutine was expected, got <Future pending
cb=[_chain_future.<locals>._call_check_cancel() at .../asyncio/futures.py:387]>
```

The lambda DID still execute in the thread pool (so SQS publish for caption
jobs went out — that's why `scene_caption` is populated in OS), but the
PATCH handler crashed with 500 right after. The drive-stt-worker outer
`except` interpreted that 500 as an STT failure and wrote
`stt_status=failed`, even though `_post_enrich_to_api` had already
succeeded against `/internal/ingest/enrich`.

Introduced 2026-03-30 in `5b3b4c1` ("fix(caption): remove vlm_tags_enabled
gate from deferred caption publishing"). Latent for ~30 days because the
two-phase pipeline (`DRIVE_SPEECH_SPLIT_ENABLED=true`) sets
`stt_already_done=True` at indexed time and publishes caption inline,
bypassing the deferred path. The legacy enrich path on 04-28 was the
first time this branch executed in volume.

**Fix:** reuse the canonical helper `_publish_scene_jobs_in_background`
from `internal_processing_router.py` — it's `async def` and awaits the
executor, so `create_task` receives a coroutine.

**Regression test:** `services/api/tests/test_internal_router_deferred_caption.py`
pins the helper as a coroutine function AND documents the failure mode of
the bad pattern.

## Root cause #2 — unconditional ffmpeg audio extraction

**File:** `services/drive-transcode-worker/src/tasks/transcode.py:214-235` (pre-fix).

```python
subprocess.run(
    ["ffmpeg", "-i", proxy, "-vn", "-acodec", "pcm_s16le",
     "-ar", "16000", "-ac", "1", "-y", audio_path],
    check=True, ...
)
```

ffmpeg returns exit 234 (EINVAL — "no audio stream to encode") on inputs
with no audio track. `check=True` then raises `CalledProcessError` out of
`_process_single_transcode`, and the `try/except` at function level marks
the file `processing_status=failed` AND discards the scenes/keyframes that
were already produced above.

Common offender: dashcam / black-box / screen-recording footage. The
staging incident batch had 155 such files.

**Fix:** factor audio extraction into a `_extract_audio_to_s3` helper that
checks `proxy_probe.has_audio` first (the field is already populated by
`heimdex_media_pipelines.transcoding.probe_video`). When absent, the
helper logs and returns `None` — and `publish_enrichment_jobs` already
treats a null `audio_s3_key` as "skip STT for this video," so the rest of
the pipeline proceeds normally.

**Regression test:** `services/drive-transcode-worker/tests/test_audio_extraction_gate.py`
covers the no-audio skip, the with-audio happy path, and the
ffmpeg-fails-on-real-audio failure-propagation case.

## Defense-in-depth follow-ups (NOT in this PR)

1. **Persist `last_error` to `drive_files`** — the 155 stuck dashcam rows
   show `enrichment_error=NULL` even though `worker_events` recorded the
   ffmpeg failure. Operators reading the DB can't see why the pipeline
   stalled. Either dual-write last_error on transcode failure, or add a
   `/api/admin/health` view that joins `drive_files` to the latest
   `worker_events` row per file_id.
2. **Distinguish "STT ran with empty result" from "STT never ran"** —
   in OpenSearch both look like `transcript_raw=''`. Emit a worker_event
   `scene_enrich_zero_segments` at WARN level when whisper produces no
   segments so empty audio (silent video, foreign-language whisper miss)
   is debuggable separately from never-ran.
3. **Hide transcript section in the UI for `content_type='image'` scenes**
   — image scenes legitimately have `transcript_raw=''`. The current
   batch on staging is dominated by 160 image rows; if the UI shows an
   empty transcript card on each one it amplifies the "STT is missing"
   perception.

## Repair script for the 8 stt=failed videos

The OpenSearch transcripts are empty AND PG status is wrong. Whether the
audio actually had Korean speech needs a manual whisper re-run with
`language=auto` to confirm. Procedure:

```
docker compose exec -T api python -m \
  scripts.repair_scene_manifest_and_requeue_stt \
  --org-slug devorg --video-ids gd_4d8abe5c8e0150e8,gd_0abd08ef402eeb36,...
```

Run on one video first to verify the asyncio fix is deployed before
fanning out.
