# Phase 1b-1: STT Worker DB-Free

## Summary

Decouples `drive-stt-worker` from direct database access, following the same pattern established in Phase 1a (caption worker). The STT worker now communicates with the API server exclusively via internal HTTP endpoints, using the shared `InternalAPIClient` from the worker SDK.

Additionally, the internal API layer (schemas, router, SDK client) was **generalized** from caption-only to support all job types (caption, stt, ocr), preparing the ground for Phase 1b-2 (OCR worker).

## What Changed

### API: Generalized Internal Drive Endpoints

**Modified files:**
- `app/modules/drive/internal_schemas.py` — Generalized from caption-specific to generic job types
- `app/modules/drive/internal_router.py` — Generalized status update logic with error column mapping

**Schema changes:**

| Before (Phase 1a) | After (Phase 1b-1) | Notes |
|--------------------|---------------------|-------|
| `caption_status: str` on `UpdateJobStatusRequest` | `job_type: JobType`, `status: EnrichmentStatus`, `error: Optional[str]` | Generic for caption/stt/ocr |
| N/A | `audio_s3_key: Optional[str]` on `ClaimedFileInfo` | STT needs audio path |
| N/A | `audio_s3_key: Optional[str]` on `DriveFileMetadataResponse` | Consistent metadata |

**Router changes:**

- Added `_ERROR_COLUMN_MAP` to route error field writes: `caption→caption_error`, `stt→enrichment_error`, `ocr→enrichment_error`
- `update_job_status` endpoint now accepts any `job_type` and computes `enrichment_state` by overriding only the requesting job type's status in the state computation
- `claim` response and `get_file` response now include `audio_s3_key`
- Renamed FastAPI `status` import to `http_status` to avoid shadowing with Pydantic's `request.status` field

### Worker SDK: Generalized InternalAPIClient

**Modified file:** `services/worker_sdk/src/heimdex_worker_sdk/internal_api.py`

- `update_job_status(file_id, *, job_type, status, error=None)` — keyword-only generic signature (replaces `caption_status`/`caption_error` positional args)
- `ClaimedFile` dataclass — added `audio_s3_key: Optional[str]` field
- Retry behavior unchanged (0.5s base, 8s max, 3 retries on 502/503/504/429)

### Caption Worker: Updated Call Sites

**Modified file:** `services/drive-caption-worker/src/tasks/caption.py`

- All 6 `update_job_status()` call sites updated from positional `caption_status`/`caption_error` args to new keyword-only `job_type="caption"`, `status=`, `error=` signature
- No behavioral change; purely a signature migration

### STT Worker: DB Removed

**Modified files:**
- `src/worker.py` — Replaced `create_async_engine` + `async_sessionmaker` with `InternalAPIClient`
- `src/tasks/stt.py` — Replaced all `DriveFileRepository` calls with `api_client` HTTP calls

**Replaced patterns:**

| Before (DB) | After (HTTP) |
|-------------|-------------|
| `file_repo.claim_stt_pending_files(limit)` | `api_client.claim_jobs("stt", limit)` |
| `file_repo.update_stt_enrichment_status(file_id, "done")` | `api_client.update_job_status(file_id, job_type="stt", status="done")` |
| `file_repo.update_stt_enrichment_status(file_id, "failed", error=str(e))` | `api_client.update_job_status(file_id, job_type="stt", status="failed", error=str(e))` |
| `async with session_factory() as session:` | (removed — no async context needed) |

**Unchanged:** S3 audio download, Whisper transcription, `/internal/ingest/enrich` POST for STT data.

### Docker Compose: STT Worker Only

**Removed:**
- `DATABASE_URL` and `DATABASE_URL_SYNC` env vars
- `/opt/heimdex-api` from PYTHONPATH
- `./services/api:/opt/heimdex-api:ro` volume mount
- `postgres` from `depends_on`

**Kept:** All other workers unchanged (OCR, drive-worker still have DB access).

### Dockerfile & pyproject.toml

**Removed dependencies:** `sqlalchemy[asyncio]`, `asyncpg`, `psycopg2-binary`

## Verification Gates

| Gate | Result |
|------|--------|
| `grep create_async_engine` in stt-worker | Zero matches |
| `grep async_sessionmaker` in stt-worker | Zero matches |
| `grep app.db` in stt-worker | Zero matches |
| `grep app.modules.drive.repository` in stt-worker | Zero matches |
| `grep sqlalchemy` in stt-worker | Zero matches |
| `grep DATABASE_URL` in stt-worker | Zero matches |
| `grep DATABASE_URL` in docker-compose (stt section) | Zero matches |
| Internal drive router tests | 30 passed |
| Worker SDK tests | 26 passed |

## Test Coverage

- **30 API tests** (`test_internal_drive_router.py`): auth (4), claim (6 — now includes STT/OCR types + audio_s3_key), caption status update (5), STT status update (4 — new), get file (2), concurrency (2), schema validation (7 — now includes job_type validation)
- **26 worker SDK tests** (`test_internal_api.py`): claim (4 — includes audio_s3_key), status update (8 — caption/stt/ocr + error variants), get file (2), retry behavior (9), auth headers (1), backoff (2)
- **Concurrency test:** 10 concurrent claims with unique files → no duplicates, no deadlocks

## Key Design Decisions

1. **Generic `_ERROR_COLUMN_MAP`** — Maps `job_type` to DB column name. Caption has its own `caption_error` column; STT and OCR share `enrichment_error`. This matches the existing DB model exactly.

2. **Enrichment state recomputation** — When a job type updates its status, the endpoint reconstructs the full status map by reading all job statuses from the DB row and overriding only the updating job type's value, then feeds it to `_compute_enrichment_state()`.

3. **`http_status` alias** — FastAPI's `status` module conflicts with Pydantic model field `request.status`. Renamed import to `http_status` across all 7 usage sites.

4. **Backward-compatible generalization** — The caption worker was updated to use the new generic signature in the same PR. No separate migration needed.

## Files Modified

```
services/api/app/modules/drive/internal_schemas.py         # Generalized schemas + audio_s3_key
services/api/app/modules/drive/internal_router.py          # Generic status update + error column map
services/worker_sdk/src/heimdex_worker_sdk/internal_api.py # Generic client + audio_s3_key on ClaimedFile
services/drive-caption-worker/src/tasks/caption.py         # Updated 6 call sites to generic signature
services/drive-stt-worker/src/worker.py                    # Remove DB, use InternalAPIClient
services/drive-stt-worker/src/tasks/stt.py                 # Replace repository calls with HTTP
services/drive-stt-worker/pyproject.toml                   # Remove sqlalchemy/asyncpg deps
services/drive-stt-worker/Dockerfile                       # Remove sqlalchemy/asyncpg from fallback install
docker-compose.yml                                         # STT worker: remove DB env/volume/depends
services/api/tests/test_internal_drive_router.py           # Rewritten for generic schema + STT tests
services/worker_sdk/tests/test_internal_api.py             # Rewritten for generic client + STT/OCR tests
docs/coupling_audit/PR_phase1b1_stt_worker_db_free.md      # This file
```

## Next Steps (Phase 1b-2+)

- Migrate `drive-ocr-worker` to use internal endpoints (claim with `job_type=ocr`) — API layer already supports it
- Migrate `drive-worker` (main sync worker) — most complex, needs additional endpoints for file creation/sync
- Once all workers are DB-free, remove `database_url` from `WorkerSettings`
