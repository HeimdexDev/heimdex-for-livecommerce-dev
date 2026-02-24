# Phase 1c PR A: Internal Drive Sync Endpoints

**Status:** Complete (not yet committed)
**Date:** 2026-02-24
**Scope:** API-side only — no drive-worker changes

## Summary

Added 3 internal HTTP endpoints that allow the drive sync worker to claim connections, update sync cursors, and upsert discovered files without direct database access. This is the API-side half of the drive-worker decoupling; drive-worker migration to use these endpoints will follow in PR B.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/internal/drive/sync/claim_connection` | Claim active connections for sync (SELECT FOR UPDATE SKIP LOCKED) |
| PATCH | `/internal/drive/sync/connections/{id}/checkpoint` | Update sync cursor fields (change_token, last_sync_at) + release lease |
| POST | `/internal/drive/sync/connections/{id}/upsert_files` | Batch insert discovered files (idempotent by org_id + google_file_id) |

All endpoints require `Bearer DRIVE_INTERNAL_API_KEY` auth and are gated behind `DRIVE_CONNECTOR_ENABLED=true`.

## Design Decisions

**Connection leasing**: Reuses the same LEASE_DURATION_SECONDS (600s / 10 min) and UUID lease_token pattern from the existing job claim endpoints. Only active connections with no valid lease can be claimed. Ordering is least-recently-synced first (NULLs first for never-synced connections).

**Checkpoint semantics**: By default (`release=true`), checkpointing clears the lease and sets `last_sync_at = now()`. Setting `release=false` allows incremental checkpointing during long syncs without releasing the connection.

**File upsert idempotency**: Matches the existing drive-worker discovery logic exactly — files that already exist (by `org_id + google_file_id` unique constraint) are skipped. New files are created with `processing_status="pending"`, `stt_status="pending"`, `ocr_status="pending"`. `caption_status` is left NULL, matching existing behavior. Duplicate `provider_file_id` values within a single batch are deduplicated.

**Video ID generation**: `_drive_video_id()` replicates the canonical `worker_sdk/drive_keys.py::drive_video_id()` — `gd_{sha256(org_id:google_file_id)[:16]}`. Tested for determinism and parity.

**Auth reuse**: Imports `_verify_internal_token` from the existing `internal_router.py` to avoid duplication.

## Files Changed

### Created
- `services/api/app/modules/drive/internal_sync_schemas.py` — Pydantic DTOs (7 classes)
- `services/api/app/modules/drive/internal_sync_router.py` — FastAPI router (3 endpoints)
- `services/api/app/db/migrations/versions/021_add_connection_lease_columns.py` — Adds `lease_token` + `lease_expires_at` to `drive_connections`
- `services/api/tests/test_internal_drive_sync_router.py` — 46 tests

### Modified
- `services/api/app/modules/drive/models.py` — Added `lease_token` and `lease_expires_at` columns to `DriveConnection`
- `services/api/app/main.py` — Registered `internal_drive_sync_router` under `drive_connector_enabled` gate

## Test Coverage

| Category | Count | Details |
|----------|-------|---------|
| Claim connection | 8 | Single/multi claim, lease assignment, folder fields, cursor fields |
| Checkpoint | 7 | Release/no-release, error message, 404, lease mismatch/expiry, backward compat |
| Lease enforcement | 6 | No lease, matching token, wrong token, None token, expired lease |
| Upsert files | 11 | New/existing/mixed, empty batch, batch dedup, enqueued jobs, 404/409/400 |
| Video ID | 3 | Determinism, uniqueness, worker_sdk parity |
| Concurrency | 3 | 10 parallel claims — no duplicates, unique leases |
| Schema validation | 8 | Limit bounds, required fields, defaults, negative size |
| **Total** | **46** | |

Regression: 46 existing job router tests + 31 worker SDK tests all pass (77/77).

## Migration Path (Next PR)

PR B will modify `services/drive-worker/` to use `worker_sdk.InternalAPIClient` calling these endpoints instead of importing `DriveConnection`, `DriveFile`, and `DriveSecret` models directly.
