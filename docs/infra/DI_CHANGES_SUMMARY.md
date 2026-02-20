# Dependency Injection & Resource Lifecycle Refactor

**Date:** 2026-02-20
**Scope:** SaaS API + Drive workers (no agent/pipeline/contract changes)
**Risk:** Low — no behavior changes, only resource lifecycle management

## Problem

Runtime resources (DB engines, S3 clients, ML models, HTTP clients) were created per-request or per-job, causing:
- **Connection pool exhaustion** under load (Postgres `remaining connection slots are reserved`)
- **Unnecessary overhead** re-creating heavyweight objects on every call
- **Resource leaks** from unclosed clients (httpx, boto3)

## Changes by Phase

### P0 — DB Engine Singleton

| File | Change |
|------|--------|
| `services/api/app/config.py` | Added `db_pool_size`, `db_max_overflow`, `db_pool_timeout`, `db_pool_recycle` settings |
| `services/api/app/db/base.py` | `@lru_cache(maxsize=1)` on `get_async_engine()` + pool configuration params |
| `services/api/app/main.py` | Lifespan: removed startup dispose, added shutdown `engine.dispose()` + `close_http_client()` |

**Before:** Every call to `get_async_engine()` created a new `AsyncEngine` with its own connection pool.
**After:** Single cached engine per process, shared across all requests. Pool size controlled via env vars.

**Env vars (all optional, with sane defaults):**
```
DB_POOL_SIZE=10        # concurrent connections per process
DB_MAX_OVERFLOW=10     # burst connections above pool_size
DB_POOL_TIMEOUT=30     # seconds to wait for a connection
DB_POOL_RECYCLE=1800   # recycle connections after 30 min
```

### P1 — S3 Client Singleton

| File | Change |
|------|--------|
| `services/api/app/storage/s3.py` | `@lru_cache(maxsize=1)` on `_build_s3_client()` |

**Before:** Every `S3Client()` instantiation created a new `boto3.client('s3')`.
**After:** Single cached boto3 client shared across all `S3Client` instances. `S3Client(client=...)` injection still works for testing.

### P2 — Worker ML Model Singletons

| File | Change |
|------|--------|
| `services/drive-ocr-worker/src/worker.py` | Creates `PaddleOCR` engine once in `main()`, passes to poll loop |
| `services/drive-ocr-worker/src/tasks/ocr.py` | Accepts optional `ocr_engine` param, falls back to lazy creation |
| `services/drive-stt-worker/src/worker.py` | Creates `SttProcessor` once in `main()`, passes to poll loop |
| `services/drive-stt-worker/src/tasks/stt.py` | Accepts optional `stt_processor` param, falls back to lazy creation |

**Before:** OCR engine and STT processor were re-instantiated per file (model load = seconds).
**After:** Created once at worker startup, reused for all files in the process.

### P3 — OIDC httpx.Client Singleton

| File | Change |
|------|--------|
| `services/api/app/modules/auth/oidc.py` | Module-level `_http_client` lazy singleton via `_get_http_client()`, `close_http_client()` cleanup |
| `services/api/app/main.py` | Calls `close_http_client()` in lifespan shutdown |
| `services/api/tests/test_oidc.py` | Updated 5 tests to mock `_get_http_client` instead of `httpx.Client` context manager |

**Before:** Every JWKS fetch and userinfo call opened+closed an `httpx.Client` (TCP handshake each time).
**After:** Single persistent client reused across all OIDC calls, closed on shutdown.

## Tests Added

| File | Tests | Purpose |
|------|-------|---------|
| `services/api/tests/test_db_lifecycle.py` | 3 | Singleton verification, pool limits, session factory caching |
| `services/api/tests/test_s3_lifecycle.py` | 3 | Singleton verification, shared across instances, injection bypass |

**Full suite:** 691 passed, 7 failed (pre-existing in `test_videos.py`), 10 skipped

## Rollback

Each phase is independent. To roll back any phase:

1. **P0 (DB):** Remove `@lru_cache` from `get_async_engine()`, remove pool params, restore startup dispose in `main.py`
2. **P1 (S3):** Remove `@lru_cache` from `_build_s3_client()`
3. **P2 (Workers):** Remove engine/processor creation from `main()`, remove params from task functions (fallback will auto-create)
4. **P3 (OIDC):** Replace `_get_http_client()` calls with `with httpx.Client() as client:` blocks, remove `close_http_client()` from main.py shutdown

## What Did NOT Change

- No API endpoint signatures changed
- No request/response schemas changed
- No business logic changed
- No database migrations needed
- No new dependencies added
- Workers still function identically if `ocr_engine`/`stt_processor` params are omitted (backward-compatible fallback)
