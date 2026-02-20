# Resource Lifecycle Audit — Heimdex SaaS

**Date:** 2026-02-20
**Scope:** `dev-heimdex-for-livecommerce` (API + workers)
**Trigger:** Postgres connection pool exhaustion on staging (100/100 connections)

---

## Executive Summary

Several long-lived resources (DB engines, boto3 clients, ML models, HTTP clients) are
created per-request or per-job instead of once per process.  The most critical leak —
`create_async_engine()` per-request — caused a production outage when concurrent load
exhausted the Postgres `max_connections=100` limit.

## Resource Inventory

### CRITICAL — Caused Outage

| Resource | File | Line | Pattern | Impact |
|----------|------|------|---------|--------|
| `AsyncEngine` | `services/api/app/db/base.py` | 47-53 | `get_async_engine()` creates a **new engine (with its own connection pool) per call** | Each request gets a new pool.  Under load, pool count * pool_size > max_connections. **Root cause of the Postgres outage.** |
| `async_sessionmaker` | `services/api/app/db/base.py` | 56-62 | `get_async_session_factory()` calls `get_async_engine()` on every invocation | Amplifies the engine leak — every session factory creates a fresh engine. |

**Call chain (per request):**
```
Route → Depends(get_db_session) → get_async_session_factory() → get_async_engine() → create_async_engine()  [NEW ENGINE]
```

### HIGH — Active Leak (No Outage Yet)

| Resource | File | Line | Pattern | Impact |
|----------|------|------|---------|--------|
| `boto3.client("s3")` | `services/api/app/storage/s3.py` | 29-44 | `_build_s3_client()` creates a **new boto3 S3 client per S3Client instance** | boto3 clients hold urllib3 connection pools.  Per-request creation leaks pools. |
| `S3Client` in thumbnail route | `services/api/app/modules/thumbnails/router.py` | 116 | `S3Client(bucket=...)` per S3 thumbnail request | New boto3 client per Drive thumbnail fetch. |
| `S3Client` in playback route | `services/api/app/modules/drive/router.py` | 246 | `S3Client(bucket=...)` per playback request | New boto3 client per video stream. |
| `S3Client` in drive-worker | `services/drive-worker/src/tasks/process.py` | 126 | `S3Client(bucket=...)` per file processed | New boto3 client per Drive file ingest. |
| `S3Client` in OCR worker | `services/drive-ocr-worker/src/tasks/ocr.py` | 64 | `S3Client(bucket=...)` per OCR job | New boto3 client per OCR file. |
| `S3Client` in STT worker | `services/drive-stt-worker/src/tasks/stt.py` | 53 | `S3Client(bucket=...)` per STT job | New boto3 client per STT file. |

### MEDIUM — Per-Job Overhead (Not a Leak but Wasteful)

| Resource | File | Line | Pattern | Impact |
|----------|------|------|---------|--------|
| `PaddleOCREngine` | `services/drive-ocr-worker/src/tasks/ocr.py` | 119 | `create_ocr_engine()` per file | PaddleOCR model loaded into memory per file.  ~500MB RAM + ~5s load time per file. |
| `STTProcessor` | `services/drive-stt-worker/src/tasks/stt.py` | 120-128 | `create_stt_processor()` per file | Whisper model loaded per file.  ~1-2GB RAM + ~10s load time per file. |
| `httpx.Client` | `services/api/app/modules/auth/oidc.py` | 56, 169 | `httpx.Client()` per JWKS/userinfo call | New HTTP client per Auth0 call.  Mitigated by TTL cache (1h JWKS, 5m userinfo) but still leaks on cache miss. |

### GOOD — Already Singletons (No Action Needed)

| Resource | File | Pattern | Notes |
|----------|------|---------|-------|
| `Settings` | `app/config.py:224` | `@lru_cache` on `get_settings()` | Singleton. |
| `EmbeddingService` | `app/modules/search/embedding.py:218` | `@lru_cache(maxsize=1)` on `get_embedding_service()` | Singleton.  Model lazy-loaded on first use. |
| `OpenSearchClient` | `app/main.py:59-63` | Created in lifespan, stored in `app.state` | Singleton.  Closed on shutdown. |
| `SceneSearchClient` | `app/main.py:62-63` | Created in lifespan, stored in `app.state` | Singleton.  Closed on shutdown. |
| Worker DB engines | `drive-worker/src/worker.py:95` | `create_async_engine()` once in `main()` | Correct — engine created once per process. |
| Worker DB engines | `drive-ocr-worker/src/worker.py:71` | `create_async_engine()` once in `main()` | Correct. |
| Worker DB engines | `drive-stt-worker/src/worker.py:71` | `create_async_engine()` once in `main()` | Correct. |

---

## Fix Plan

| Priority | Fix | Files | Approach |
|----------|-----|-------|----------|
| **P0** | Singleton DB engine + pool limits | `db/base.py`, `config.py`, `main.py` | `@lru_cache` on `get_async_engine()`, add `pool_size`/`max_overflow`/`pool_timeout`/`pool_recycle` config, dispose on shutdown |
| **P1** | Singleton boto3 S3 client | `storage/s3.py` | `@lru_cache` on `_build_s3_client()` — all `S3Client` instances share one boto3 client |
| **P2** | Singleton ML models per worker | OCR + STT workers | Create OCR engine / STT processor once in `main()`, thread through to task functions |
| **P3** | Singleton httpx client for OIDC | `auth/oidc.py` | Module-level `httpx.Client` with lazy init, cleanup via atexit |
