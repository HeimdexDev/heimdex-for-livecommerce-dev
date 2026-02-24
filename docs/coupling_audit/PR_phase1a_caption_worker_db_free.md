# Phase 1a: Caption Worker DB-Free

## Summary

Decouples `drive-caption-worker` from direct database access. The worker now communicates with the API server exclusively via internal HTTP endpoints, using a new `InternalAPIClient` from the worker SDK.

## What Changed

### API: New Internal Drive Endpoints

**New files:**
- `app/modules/drive/internal_router.py` — 3 endpoints, Bearer token auth
- `app/modules/drive/internal_schemas.py` — Pydantic request/response DTOs

**Endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/internal/drive/jobs/claim` | Atomic claim with `SELECT FOR UPDATE SKIP LOCKED` |
| PATCH | `/internal/drive/jobs/{file_id}/status` | Update caption_status + recompute enrichment_state |
| GET | `/internal/drive/files/{file_id}` | Return minimal file metadata for processing |

**Auth:** Same pattern as existing `/internal/ingest/*` — Bearer token validated via `hmac.compare_digest` against `DRIVE_INTERNAL_API_KEY`.

**Design:** Claim endpoint is cross-org (no `X-Heimdex-Org-Id` header needed). Workers claim globally; `org_id` is returned in the response so the worker knows which org each file belongs to.

### Worker SDK: InternalAPIClient

**New file:** `services/worker_sdk/src/heimdex_worker_sdk/internal_api.py`

- `claim_jobs(job_type, limit)` → `list[ClaimedFile]`
- `update_job_status(file_id, caption_status, caption_error)` → `bool`
- `get_file(file_id)` → `dict`
- Bounded exponential backoff retry (0.5s base, 8s max, 3 retries)
- Retries on 502/503/504/429, ConnectionError, Timeout
- Does NOT retry on 4xx client errors
- Single `requests.Session` for connection reuse

### Caption Worker: DB Removed

**Modified files:**
- `src/worker.py` — Replaced `create_async_engine` + `async_sessionmaker` with `InternalAPIClient`
- `src/tasks/caption.py` — Replaced `DriveFileRepository` calls with `api_client.claim_jobs()` and `api_client.update_job_status()`

**Removed from caption-worker:**
- SQLAlchemy engine/session creation
- `app.db.models` import
- `app.modules.drive.repository` import
- All `session.commit()` / `session.rollback()` calls

**Unchanged:** S3 artifact behavior (same keys, same writes), `/internal/ingest/enrich` POST for scene caption data.

### Docker Compose: Caption Worker Only

**Removed:**
- `DATABASE_URL` and `DATABASE_URL_SYNC` env vars
- `/opt/heimdex-api` from PYTHONPATH
- `./services/api:/opt/heimdex-api:ro` volume mount
- `postgres` from `depends_on`

**Kept:** All other workers unchanged (STT, OCR, drive-worker still have DB access).

### Dockerfile & pyproject.toml

**Removed dependencies:** `sqlalchemy[asyncio]`, `asyncpg`, `psycopg2-binary`

## Verification Gates

| Gate | Result |
|------|--------|
| `grep create_async_engine` in caption-worker | Zero matches |
| `grep async_sessionmaker` in caption-worker | Zero matches |
| `grep app.db` in caption-worker | Zero matches |
| `grep app.modules.drive.repository` in caption-worker | Zero matches |
| `grep sqlalchemy` in caption-worker | Zero matches |
| `grep DATABASE_URL` in caption-worker | Zero matches |
| API tests (excluding live OpenSearch) | 761 passed |
| New internal drive router tests | 23 passed |
| Worker SDK tests | 56 passed |

## Test Coverage

- **23 new API tests** (`test_internal_drive_router.py`): auth (4), claim (5), status update (5), get file (2), concurrency (2), schema validation (5)
- **22 new worker SDK tests** (`test_internal_api.py`): claim (4), status update (4), get file (2), retry behavior (9), auth headers (1), backoff (2)
- **Concurrency test:** 10 concurrent claims with unique files → no duplicates, no deadlocks

## Files Created

```
services/api/app/modules/drive/internal_router.py
services/api/app/modules/drive/internal_schemas.py
services/api/tests/test_internal_drive_router.py
services/worker_sdk/src/heimdex_worker_sdk/internal_api.py
services/worker_sdk/tests/test_internal_api.py
docs/coupling_audit/PR_phase1a_caption_worker_db_free.md
```

## Files Modified

```
services/api/app/main.py                          # Register internal_drive_router
services/worker_sdk/src/heimdex_worker_sdk/__init__.py  # Export InternalAPIClient, ClaimedFile
services/drive-caption-worker/src/worker.py        # Remove DB, use InternalAPIClient
services/drive-caption-worker/src/tasks/caption.py # Replace repository calls with HTTP
services/drive-caption-worker/pyproject.toml       # Remove sqlalchemy/asyncpg deps
services/drive-caption-worker/Dockerfile           # Remove sqlalchemy/asyncpg from fallback install
docker-compose.yml                                 # Caption worker: remove DB env/volume/depends
```

## Next Steps (Phase 1b+)

- Migrate `drive-stt-worker` to use the same internal endpoints (claim with `job_type=stt`)
- Migrate `drive-ocr-worker` to use internal endpoints (claim with `job_type=ocr`)
- Migrate `drive-worker` (main sync worker) — most complex, needs additional endpoints
- Once all workers are DB-free, remove `database_url` from `WorkerSettings`
