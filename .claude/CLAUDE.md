# Heimdex for Livecommerce

Main product: multi-tenant video search platform for Korean live commerce.

## Quick Reference

```bash
# Local development
docker compose up -d
# Web: http://localhost:3000
# API: http://devorg.app.heimdex.local:8000 (add to /etc/hosts)
# OpenSearch: http://localhost:9200
# MinIO: http://localhost:9001

# First-time setup
make seed               # Run migrations + seed data

# VERIFICATION (run before pushing)
make verify             # All-in-one: tests + build + coupling + E2E smoke

# Individual quality gates
make check              # Tests + build + coupling
make test               # Backend unit tests
make test-integration   # Integration tests (needs OpenSearch)
make build              # Next.js type-check + build
make lint               # Backend (ruff) + Frontend (eslint)
make check-coupling     # Worker-API coupling check

# E2E tests (Playwright — 15 tests across 3 files)
make e2e                # All E2E tests
make e2e-smoke          # Smoke tests only (< 60s)
make e2e-consistency    # Feature consistency tests
make e2e-visual         # Visual regression (compare against baselines)
make e2e-visual-update  # Update visual regression baselines
make e2e-staging        # Run smoke + consistency against staging

# Search quality regression
make search-quality     # Golden queries: BM25, semantic, hybrid

# Post-deploy staging verification
../../scripts/verify-staging-deploy.sh          # Wait for deploy + run E2E
../../scripts/verify-staging-deploy.sh --skip-wait  # Just run E2E on staging

# Playwright setup (first time only)
cd e2e && npm install && npx playwright install chromium
```

## Architecture

### Monorepo Structure

```
services/
├── api/              # FastAPI backend (Python 3.11)
│   ├── app/
│   │   ├── modules/  # Domain modules (24+: auth, search, drive, ingest, people, etc.)
│   │   ├── db/       # SQLAlchemy models + Alembic migrations (40+ versions)
│   │   └── config.py # All env-driven settings
│   └── tests/
├── web/              # Next.js 14 frontend (TypeScript)
│   └── src/
├── drive-worker/     # Main orchestrator: Google Drive sync + SQS consumer
│   └── src/tasks/scene_split.py  # Speech-aware scene split task handler
├── drive-transcode-worker/   # FFmpeg video transcoding
├── drive-visual-embed-worker/ # SigLIP2 visual embeddings
├── drive-face-worker/        # Face detection + clustering
├── youtube-worker/           # YouTube content sync
├── shorts-render-worker/     # Short-form video generation
├── worker_sdk/               # Shared worker utilities
└── (deprecated: drive-caption-worker, drive-stt-worker, drive-ocr-worker, llama-caption-server, worker)
```

### Two-Phase Speech-Aware Scene Splitting (when `DRIVE_SPEECH_SPLIT_ENABLED=true`)

1. drive-worker uploads audio → enqueues STT job with `callback_mode="scene_split"`
2. STT worker transcribes on GPU → uploads result to S3 (`{org}/drive/stt/{video_id}/stt_result.json`) → callbacks API
3. drive-worker runs `split_scenes()` with speech data from S3

Processing statuses: `awaiting_stt`, `awaiting_scene_split`
DB columns added (migration 039): `stt_result_s3_key`, `stt_requested_at`
SQS: `scene_split.job_created` message type on processing queue; `callback_mode` field on STT queue messages
Resplit uses `split_scenes()` (not `detect_scenes()`), loads STT from S3

### Key Principle: Workers MUST NOT import API database models

This is enforced by `worker-coupling-check.yml` in CI. Workers communicate with the API exclusively via HTTP (`/internal/ingest/*` endpoints).

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, SQLAlchemy 2.0, Alembic, Python 3.11 |
| Frontend | Next.js 14.1, React 18, TypeScript 5.3, Tailwind 3.4 |
| Database | PostgreSQL 16 + pgvector |
| Search | OpenSearch 2.11 (hybrid BM25 + kNN, RRF fusion, Nori Korean) |
| Text Embeddings | `intfloat/multilingual-e5-large` (1024-dim) |
| Visual Embeddings | `google/siglip2-base-patch16-256` (768-dim) |
| Queue | AWS SQS (ElasticMQ for local dev) |
| Storage | AWS S3 / MinIO (local) |
| Auth | Auth0 (production) / dev-login (local) |
| Monitoring | Sentry, structlog |
| Scene Splitting | Speech-aware two-phase pipeline: drive-worker → STT worker → split_scenes() |

## Dependencies on Other Repos

Both `heimdex-media-contracts` and `heimdex-media-pipelines` are **mounted as Docker volumes** and installed as editable packages:

```yaml
# docker-compose.yml
volumes:
  - ../heimdex-media-contracts:/opt/heimdex-media-contracts:ro
  - ../heimdex-media-pipelines:/opt/heimdex-media-pipelines:ro
```

**Before modifying contracts or pipelines**, verify changes don't break this repo's API or workers.

## Multi-Tenancy

Subdomain-based: `{org-slug}.app.heimdex.co`. API extracts org from `Host` header. All data is org-scoped.

Local dev requires `/etc/hosts` entry: `127.0.0.1 devorg.app.heimdex.local`

## Docker Services

| Service | Port | Profile | Status |
|---|---|---|---|
| api | 8000 | default | Active |
| web | 3000 | default | Active |
| postgres | 5432 | default | Active |
| opensearch | 9200 | default | Active |
| minio | 9000/9001 | default | Active |
| drive-worker | — | default | Active |
| drive-transcode-worker | — | default | Active |
| shorts-render-worker | — | default | Active |
| youtube-worker | — | youtube | Optional |
| drive-visual-embed-worker | — | ec2-legacy | Active (local dev only) |
| drive-face-worker | — | ec2-legacy | Active (local dev only) |
| face-worker | — | face-dev | Deprecated (sleeps) |
| drive-caption-worker | — | ec2-legacy | Deprecated (Aircloud+) |
| drive-stt-worker | — | ec2-legacy | Deprecated (Aircloud+) |
| drive-ocr-worker | — | ec2-legacy | Deprecated (Aircloud+) |

## Search

Hybrid retrieval: BM25 (lexical) + kNN (semantic) with Reciprocal Rank Fusion.

- `SEARCH_DEFAULT_MODE`: `segments` or `scenes`
- Alpha slider: 0 = pure lexical, 1 = pure semantic, 0.5 = balanced
- Index versioning with alias promotion for zero-downtime migration
- Promote: `python -m app.modules.search.promote_alias`

## Deployment

| Environment | Domain | Trigger |
|---|---|---|
| Staging | `*.app.heimdexdemo.dev` | Auto on push to `main` |
| Production | `livenow.app.heimdex.co` | Manual via GitHub Actions |

**Pushing to main triggers staging deploy.** Batch commits during rapid development to avoid deploy storms.

Production MUST use `--no-deps` flag in all Docker Compose commands. Production uses `docker-compose.prod.yml` overlay (on EC2, not in repo).

## CI/CD Workflows

| Workflow | Trigger | Purpose |
|---|---|---|
| `deploy-staging.yml` | Push to main | Auto-deploy to staging EC2 |
| `deploy-production.yml` | Manual dispatch | Deploy to production EC2 |
| `build-gpu-images.yml` | Manual / code change | Build GPU worker images for GHCR |
| `worker-coupling-check.yml` | PR / push | Verify workers don't import API DB models |
| `analytics-export.yml` | Scheduled | Export analytics to S3 |
| `search-quality.yml` | Manual | Search quality regression tests |

## Key Configuration

All settings are environment-driven via `services/api/app/config.py`.

Critical env vars:
- `AUTH0_ENABLED` — `false` for local, `true` for staging and production
- `AIRCLOUD_ENABLED` — `true` to use Aircloud GPU workers
- `EMBEDDING_USE_MOCK` — `true` for tests without loading models
- `ENVIRONMENT` — affects auth validation behavior
- `NEXT_PUBLIC_*` — baked into Next.js at BUILD time (must rebuild web container to change)
- `DRIVE_SPEECH_SPLIT_ENABLED` — `false` by default; enables two-phase speech-aware scene splitting
- `drive_split_preset` — `default/fine/coarse/visual_only`; set per org in org settings
- `drive_stt_timeout_seconds` — timeout for STT worker callback before scene split proceeds

## Infrastructure Access

### Staging
- **Host**: `3.34.75.63` (heimdex-staging, ap-northeast-2)
- **SSH**: `ssh -i ~/.ssh/heimdex-staging.pem ec2-user@3.34.75.63`
- **Project path**: `/opt/heimdex/dev-heimdex-for-livecommerce`
- **Docker**: Full stack including postgres, opensearch, minio containers
- **Auth**: `AUTH0_ENABLED=true` — Auth0 login required (same as production)

### Production
- **Host**: `54.116.79.254` (livenow-prod, ap-northeast-2)
- **SSH**: No local PEM — use EC2 Instance Connect:
  ```bash
  ssh-keygen -t rsa -b 2048 -f /tmp/heimdex-prod-temp -N "" -q
  aws ec2-instance-connect send-ssh-public-key \
    --instance-id i-02f0e86a7a50b283b \
    --instance-os-user ec2-user \
    --ssh-public-key file:///tmp/heimdex-prod-temp.pub \
    --region ap-northeast-2
  ssh -i /tmp/heimdex-prod-temp ec2-user@54.116.79.254  # within 60s
  ```
- **Project path**: `/opt/heimdex/dev-heimdex-for-livecommerce`
- **Docker**: Only `api`, `web`, `drive-worker` — no postgres/opensearch containers (external AWS services)
- **Auth**: `AUTH0_ENABLED=true` — dev-login returns 403
- **Compose files**: `docker-compose.yml` + `docker-compose.override.yml` + `docker-compose.release.yml`

### Running Scripts on Staging/Production
- Staging: scripts can run inside containers via `docker compose exec -T api python -`
- Production: same pattern, but pipe script via stdin (no volume mount for scripts/)
- DB URL uses `postgresql+asyncpg://` — strip `+asyncpg` for psycopg2: `.replace("postgresql+asyncpg://", "postgresql://")`

## Cross-Repo Dependency: heimdex-media-contracts

Contracts are **volume-mounted** into Docker containers, NOT installed from PyPI during builds. However, `pyproject.toml` version constraints are still checked during `docker build` (pip install step). The Dockerfile strips the contracts dependency via `sed`, but if any other dep transitively requires contracts, the PyPI version is used.

**Rule**: Never set `>=X.Y.Z` in pyproject.toml if that version doesn't exist on PyPI yet. The current safe floor is `>=0.8.0` (latest on PyPI). To publish a new version, tag `vX.Y.Z` in the contracts repo.

## Data Backfill Patterns

When fixing data that lives in both PostgreSQL and OpenSearch:
1. **Always update both** — DB is source of truth, but OpenSearch has a copy baked in at ingest time
2. **OpenSearch bulk update**: Use `bulk_partial_update_scenes()` or direct `client.bulk()` with `{"update": ...}` actions
3. **Find scenes by video**: `scene_client.find_scene_ids_by_video_id(org_id, video_id)`
4. **Production has no postgres container** — use `docker compose exec -T api python -` with psycopg2

## Anti-Patterns

- Workers importing from `app.db` or `app.models` (coupling check will catch this)
- Running `docker compose up -d` without `--no-deps` on production
- Confusing `heimdex-*` (staging) and `livenow-*` (production) SQS queue prefixes
- Changing `NEXT_PUBLIC_*` vars without rebuilding the web container
- Setting `AUTH0_ENABLED=false` with `ENVIRONMENT=staging` or `production` (crashes API)
- Setting `heimdex-media-contracts>=X.Y.Z` where X.Y.Z is not on PyPI (breaks Docker build)
- Updating DB without updating OpenSearch (stale search results / dates)
- Google Drive incremental sync: forgetting to add new fields to the `changes().list()` fields parameter (only full scan fields auto-include everything)
- Setting `DRIVE_SPEECH_SPLIT_ENABLED=true` without the STT worker deployed (videos get stuck in `awaiting_stt`)

## Documentation

- `/README.md` — Quick start, multi-tenancy invariants, API reference
- `/docs/architecture.md` — System design, search algorithm, data models
- `/docs/AUTH0_SETUP.md` — Auth0 integration guide
- `/docs/search-quality.md` — Search quality evaluation
- `/docs/SCENE_GROUPING_ARCHITECTURE.md` — Scene clustering logic
- Workspace `docs/` — See [ECOSYSTEM.md](../../docs/ECOSYSTEM.md) for full index
