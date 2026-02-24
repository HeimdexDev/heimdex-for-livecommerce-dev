# PR: Post-Phase 1 Cleanup — Remove Dead DB Settings + Add Coupling Guardrails

**Date:** 2026-02-24
**Scope:** worker_sdk, CI, Makefile, scripts
**Breaking changes:** None

## Context

Phase 1 DB-decoupling is complete: all 4 workers (drive, caption, STT, OCR) communicate exclusively via internal HTTP API. This PR removes leftover dead configuration and adds permanent guardrails to prevent regression.

## What Was Removed

### worker_sdk/settings.py — 3 dead fields

| Field | Why Dead |
|-------|----------|
| `database_url` | Workers no longer import `app.db`. All DB access goes through internal HTTP API. |
| `database_url_sync` | Same as above. |
| `drive_sa_encryption_key` | Token broker endpoint handles decryption server-side. Workers never see raw keys. |

Also removed the stale comment `# --- Database (needed while workers still import app.db.models) ---` and updated the module docstring to document the post-Phase 1 architecture.

### worker_sdk/tests/test_settings.py — 1 dead test

Removed `test_default_database_url` which tested the deleted `database_url` field.

## What Was Added

### scripts/check_no_worker_db_coupling.sh

Guardrail script that checks 4 categories of DB coupling:

1. **Worker source code** — scans `services/drive-*-worker/src/` for forbidden imports (sqlalchemy, asyncpg, psycopg2, app.db, app.modules, app.config, DATABASE_URL)
2. **Worker package files** — scans `pyproject.toml` and `Dockerfile` for DB dependencies
3. **docker-compose.yml** — checks each worker service for DATABASE_URL env vars, `/opt/heimdex-api` mounts, postgres dependencies, DRIVE_SA_ENCRYPTION_KEY
4. **worker_sdk settings** — checks for `database_url` field definitions

Exit code 0 = clean, 1 = violations found.

### .github/workflows/worker-coupling-check.yml

GitHub Actions workflow that runs the guardrail on every PR touching:
- `services/drive-*-worker/**`
- `services/worker_sdk/**`
- `docker-compose.yml`
- The guardrail script or workflow itself

### Makefile — `check-coupling` target

Added to `make check` pipeline. Runs locally via `make check-coupling`.

## Verification

### Guardrail script
```
$ bash scripts/check_no_worker_db_coupling.sh
=== Checking worker source code for DB coupling ===
=== Checking worker package files for DB dependencies ===
=== Checking docker-compose.yml for worker DB wiring ===
=== Checking worker_sdk settings for dead DB fields ===
PASSED: No worker DB coupling detected
```

### Test suite (193/193 pass)
```
worker_sdk tests:  81 passed
sync router:       51 passed
processing router: 15 passed
enrichment router: 46 passed
```

## Rollback Plan

1. Revert this commit
2. Re-add `database_url`, `database_url_sync`, `drive_sa_encryption_key` to `WorkerSettings`
3. Re-add `test_default_database_url` test
4. Delete `scripts/check_no_worker_db_coupling.sh`
5. Delete `.github/workflows/worker-coupling-check.yml`
6. Revert Makefile changes

No runtime behavior changes — rollback is purely additive (restoring dead fields) and subtractive (removing guardrails).

## Files Changed

| File | Change |
|------|--------|
| `services/worker_sdk/src/heimdex_worker_sdk/settings.py` | Removed 3 dead DB fields, updated docstring |
| `services/worker_sdk/tests/test_settings.py` | Removed dead `test_default_database_url` |
| `scripts/check_no_worker_db_coupling.sh` | **NEW** — coupling guardrail script |
| `.github/workflows/worker-coupling-check.yml` | **NEW** — CI workflow |
| `Makefile` | Added `check-coupling` target to `make check` |
| `docs/coupling_audit/PR_phase1_cleanup_guardrails.md` | **NEW** — this document |
