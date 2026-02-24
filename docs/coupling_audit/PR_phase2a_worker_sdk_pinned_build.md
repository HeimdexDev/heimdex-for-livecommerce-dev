# Phase 2a: Worker SDK Pinned Build

## Summary

Production Docker images now bake `heimdex_worker_sdk` as a wheel at build time.
Dev workflow preserved via `docker-compose.override.yml` for live SDK editing.

## Motivation

Before this change, all 4 worker containers installed `worker_sdk` at **runtime**
via an editable mount + `pip install --no-deps -e`. This meant:

- Production images had no SDK baked in — they depended on a host volume mount
- Container startup was slower (pip install on every start)
- No version pinning — whatever was on disk was what ran
- Build reproducibility was impossible to verify

## What Changed

### 1. worker_sdk packaging fix

- Added missing `requests>=2.31` to `pyproject.toml` dependencies
- `internal_api.py` imports `requests` but it was never declared

### 2. Multi-stage Dockerfiles (all 4 workers)

Each worker Dockerfile now uses a 2-stage build:

```
Stage 1 (sdk-builder):
  python:3.11-slim → copy worker_sdk source → build wheel

Stage 2 (final):
  python:3.11-slim → install wheel → install worker deps → copy worker src
```

Workers affected:
- `services/drive-worker/Dockerfile`
- `services/drive-ocr-worker/Dockerfile`
- `services/drive-caption-worker/Dockerfile`
- `services/drive-stt-worker/Dockerfile`

### 3. docker-compose.yml changes (per worker)

| Field | Before | After |
|-------|--------|-------|
| `build.context` | `./services/<worker>` | `.` (repo root) |
| `build.dockerfile` | `Dockerfile` | `services/<worker>/Dockerfile` |
| `PYTHONPATH` | `/app:/opt/heimdex-worker-sdk/src` | `/app` |
| SDK volume mount | present | **removed** |
| SDK pip install in command | present | **removed** |

Note: `heimdex-media-contracts` and `heimdex-media-pipelines` mounts remain
(Phase 2b scope).

### 4. docker-compose.override.yml (NEW)

Auto-loaded by `docker compose up`. Re-adds SDK volume mount + editable install
for local development. To run prod-like:

```bash
docker compose -f docker-compose.yml up
```

### 5. .dockerignore (NEW)

Excludes `.git`, `data/`, `docs/`, `node_modules/`, `__pycache__/`, etc.
from the Docker build context (now repo root).

## Files Changed

| File | Change |
|------|--------|
| `services/worker_sdk/pyproject.toml` | Added `requests>=2.31` |
| `services/drive-worker/Dockerfile` | Rewritten: multi-stage |
| `services/drive-ocr-worker/Dockerfile` | Rewritten: multi-stage |
| `services/drive-caption-worker/Dockerfile` | Rewritten: multi-stage |
| `services/drive-stt-worker/Dockerfile` | Rewritten: multi-stage |
| `docker-compose.yml` | Updated 4 worker services |
| `docker-compose.override.yml` | **NEW**: Dev SDK override |
| `.dockerignore` | **NEW**: Build context exclusions |

## Verification

- [x] 81/81 worker_sdk tests pass
- [x] 112/112 internal drive API tests pass
- [x] Coupling guardrail: PASSED
- [x] `docker compose -f docker-compose.yml config` validates
- [x] `docker compose -f docker-compose.yml -f docker-compose.override.yml config` validates
- [ ] `docker build` (requires Docker daemon — verify on CI/staging)

## Behavior Changes

**None.** This is a packaging/build change only. No code logic was modified.

## Out of Scope (Phase 2b)

- `heimdex-media-contracts` wheel packaging
- `heimdex-media-pipelines` wheel packaging
- Removing contracts/pipelines volume mounts from base compose
