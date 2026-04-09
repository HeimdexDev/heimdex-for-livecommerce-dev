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

# Backfill enrichments for existing videos
docker compose exec -T api python -m app.cli.backfill --target ai_tags --dry-run
docker compose exec -T api python -m app.cli.backfill --target ai_tags --org livenow --batch-size 20
docker compose exec -T api python -m app.cli.backfill --target caption --since 2026-03-01 --resume
# Targets: ai_tags, caption, visual_embed, stt, ocr
# Flags: --org, --since, --until, --library, --limit, --batch-size, --delay, --dry-run, --resume, --skip-idempotency

# Backfill face thumbnails to S3
docker compose exec -T api python -m app.cli.backfill_face_thumbnails_to_s3 --dry-run
docker compose exec -T api python -m app.cli.backfill_face_thumbnails_to_s3
# Flags: --dry-run, --org <org_id>, --skip-existing

# Export search analytics to S3 (Parquet)
docker compose exec -T api python -m app.cli.export_analytics --dry-run
docker compose exec -T api python -m app.cli.export_analytics                   # exports yesterday
docker compose exec -T api python -m app.cli.export_analytics --date 2026-03-15 # specific date
# S3 path: s3://{bucket}/analytics/search_events/year={Y}/month={M}/day={D}/{date}.parquet
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

### Tags (keyword_tags, product_tags, ai_tags) — HIDDEN FROM UI

All three tag types are **hidden from the frontend** as of 2026-04-09. Customer feedback: tags are not useful in their current state. Data remains in OpenSearch — backend generation, API responses, and search filters are untouched. Re-enable by restoring the removed JSX blocks when tag quality improves.

| Type | Field | Source | UI Status |
|---|---|---|---|
| Keyword tags | `keyword_tags` | VLM or rule-based fallback | Hidden |
| Product tags | `product_tags` | VLM or rule-based fallback | Hidden |
| AI tags | `ai_tags` | VLM free-form Korean | Hidden |

**VLM Model**: Qwen2.5-VL-7B-Instruct with bitsandbytes 4-bit quantization (~6-7GB VRAM). Runs on Aircloud RTX 4070 TI Super (16GB VRAM, 58GB RAM). Engine key: `qwen2vl`. Staging endpoint: `74cc374a-16fe-4c94-97d0-c78e9746fea5`.

Feature flags: `VLM_TAGS_ENABLED` (enables VLM tag extraction), `AI_TAGS_ENABLED` (enables free-form ai_tags). Both must be `true` for ai_tags to flow. These control backend generation only — UI display was removed separately.

### Color Search (4th RRF Dimension)

Dominant color family search in image search mode. Users click a broad color family chip (e.g. "분홍/Pink") and get images whose overall visual impression is dominated by that family. Tiny accents rank low.

- **Families**: 12 families defined in `COLOR_FAMILIES` dict in `color_extraction.py`: red, pink, orange, yellow, green, teal, blue, purple, brown, white, gray, black
- **Query flow**: Color picker sends `color_family` param (e.g. `"pink"`) → `family_to_color_histogram()` builds broad 27-dim query vector → `search_color_vector()` kNN → 4th signal in weighted RRF fusion. `color_hex` still supported for backward compat (falls back to `hex_to_color_histogram()`).
- **Index fields**: `color_embedding` (knn_vector 27-dim), `dominant_colors` (keyword, display only)
- **Extraction**: `color_extraction.py` — pure functions, no GPU, no scikit-learn. Pillow only. k-means → HSL histogram.
- **Weights**: Color-only search = 100% color. Color + text = 40% color, 60% split across BM25/E5/SigLIP2
- **Backfill**: `python -m app.cli.backfill_colors_direct` — runs in API container, reads keyframes from S3, no SQS needed
- **Scope**: Image search mode only. Video scenes do not need color backfill.
- **Two endpoints**: Both `/api/search` and `/api/search/scenes` accept `color_family`. Frontend uses `/scenes`.

### Video Summary (OpenAI gpt-4o-mini)

AI-generated 2-4 sentence Korean summary of video content, replacing the old concatenated scene captions in "행동 요약".

- **Module**: `app/modules/video_summary/` — isolated, no imports from workers/ingest/scene_overrides
- **OpenAI client**: `openai_client.py` has zero internal imports — fully mockable
- **Storage**: `video_summaries` table in Postgres (source of truth), `video_summary` field denormalized to all scenes in OpenSearch
- **Override pattern**: `summary_override` column for user edits (NULL = use AI summary). Same pattern as scene_overrides.
- **Staleness**: `input_hash` (SHA-256 of sorted captions) detects when captions changed since generation
- **Prompt**: Versioned (`prompts.py`). Current: `v1`. Can batch-regenerate with new versions.
- **Endpoints**: `GET/POST/PATCH/DELETE /api/videos/{video_id}/summary[/generate|/override]`
- **Frontend**: Lazy generation on first view. InlineEditField for editing. "재생성" button when stale.
- **BM25**: `video_summary` added to lexical search `should` clauses with boost 0.5
- **Backfill**: Direct script (not SQS) — generates via OpenAI API, stores in Postgres, denormalizes to OpenSearch. 69/296 videos backfilled on staging (227 had <2 captions).
- **Cost**: ~$0.00014/video (gpt-4o-mini). Full corpus under $15.
- **Config**: `VIDEO_SUMMARY_ENABLED`, `OPENAI_API_KEY`, `VIDEO_SUMMARY_MODEL` (default: gpt-4o-mini)

### Video Playback Aspect Ratio

Video player container respects org `thumbnail_aspect_ratio` setting. Affects VideoDetailPage and Shorts Editor PreviewPanel. 9:16 orgs get portrait player, 16:9 orgs get landscape.

### Backfill CLI (`services/api/app/cli/backfill.py`)

**Living script** — evolve this CLI whenever new enrichment types are added. When a code change affects how existing data is indexed, stored, or enriched, add a new target to `TARGETS` in `backfill.py` and run a backfill.

**When to backfill:** Any change that introduces a new field, modifies enrichment output, or changes how data is indexed requires backfilling existing videos. Use the backfill CLI — do not write one-off scripts.

**How to add a new target:**
1. Add a `BackfillTarget` entry to `TARGETS` dict in `backfill.py`
2. Map it to the correct SQS `job_types` and `status_field` for idempotency
3. Test with `--dry-run` first, then `--limit 5` on staging

Current targets: `ai_tags`, `caption`, `visual_embed`, `stt`, `ocr`, `color`. All flow through SQS + worker infrastructure except `color` which has a direct backfill script (`backfill_colors_direct.py`) that runs in the API container. `ai_tags` = re-captioning with `AI_TAGS_ENABLED=true`.

### Face Profile Thumbnail Selection

Users can choose representative face images via gallery picker or custom upload:

- **Gallery**: `GET /api/people/{id}/exemplars` returns pre-generated face crops sorted by quality
- **Select**: `PATCH /api/people/{id}/thumbnail` with exemplar_id
- **Upload**: `POST /api/people/{id}/thumbnail` (multipart, max 5MB, resize to 512x512 JPEG)
- **Reset**: `DELETE /api/people/{id}/thumbnail` reverts to auto-selection

Override protection: `FaceIdentity.thumbnail_source` column (`auto`/`exemplar`/`upload`). When not `auto`, face worker's internal upload endpoint returns `{"stored": false, "skipped": "user_override"}`. Merge preserves user-selected thumbnails. Delete cleans up exemplar crop files.

Disk layout: `/data/thumbnails/{org_id}/faces/exemplars/{exemplar_uuid}.jpg`
S3 layout: `{org_id}/faces/{cluster_id}.jpg`, `{org_id}/faces/exemplars/{exemplar_id}.jpg`

Storage: Dual-write (disk + S3). Reads check disk first, fall back to S3. When `FACE_THUMBNAIL_S3_PRIMARY=true`, reads from S3 first with disk fallback. S3 cleanup on delete/merge. Backfill existing disk thumbnails with `backfill_face_thumbnails_to_s3.py`.

### Highlight Reel (when `HIGHLIGHT_REEL_ENABLED=true`)

Auto-generates a highlight video from a face profile. Uses the "Max-Diversity Run Sampler" algorithm to select scenes across multiple videos.

- **Preview**: `POST /api/people/{id}/highlight-reel/preview` — returns clip selection for review
- **Render**: `POST /api/people/{id}/highlight-reel/render` — submits to existing shorts render pipeline

Architecture: Hexagonal — domain algorithm (`highlight_reel/domain.py`) is pure Python with zero I/O imports. Port protocol (`port.py`) defines data access interface. Adapter (`adapter.py`) implements it with OpenSearch + DB. Service layer orchestrates. No direct imports from `shorts_render` internals.

User controls: duration (30s-5min), per-video exclusions respected, clip removal in preview. Rendered videos appear on shorts page with progress tracking.

### Shorts Timeline Editor

Timeline-based video editor at `/shorts/editor` for composing short-form videos from scenes.

- **Route**: `/shorts/editor?videoId=X&sceneIds=a,b,c` or `?shortId=Y`
- **Module**: `services/web/src/features/shorts-editor/` (self-contained, 28 files)
- **State**: `useEditorState` reducer with 16 actions (clip CRUD, trim, reorder, subtitle CRUD)
- **Preview**: Multi-clip playback via `usePlaybackSync` — switches `<video>` source at clip boundaries
- **Timeline**: Visual clip blocks + subtitle bars, zoom 25-300%, drag-and-drop reorder via `@dnd-kit/sortable`
- **Render**: Builds `CompositionSpec` → `POST /api/shorts/render` → existing FFmpeg pipeline
- **API client**: `lib/api/shorts-render.ts` (submitRender, listRenderJobs, getShortComposition)
- **Backend**: `GET /api/shorts/{short_id}/composition` generates or retrieves CompositionSpec
- **Entry points**: ShortsCreatePage ("타임라인에서 편집"), SavedShortsPage ("편집"), ShortsPlanPanel ("Edit in Timeline")
- **Keyboard**: Space (play/pause), Delete (remove selected), Escape (deselect)

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

`heimdex-media-contracts`, `heimdex-media-pipelines`, and `heimdex-worker-sdk` are **mounted as Docker volumes** via `docker-compose.override.yml` and installed as editable packages:

```yaml
# docker-compose.override.yml
volumes:
  - ../heimdex-media-contracts:/opt/heimdex-media-contracts:ro
  - ../heimdex-media-pipelines:/opt/heimdex-media-pipelines:ro
  - ../heimdex-worker-sdk:/opt/heimdex-worker-sdk:ro
```

**Before modifying contracts, pipelines, or worker-sdk**, verify changes don't break this repo's API or workers.

## Multi-Tenancy

Subdomain-based: `{org-slug}.app.heimdex.co`. API extracts org from `Host` header. All data is org-scoped.

### Frontend API Routing

`getApiBaseUrl()` in `services/web/src/lib/api/utils.ts` resolves the API base URL dynamically:
- `NEXT_PUBLIC_API_URL` env var if set (local dev: `http://devorg.app.heimdex.local:8000`)
- `window.location.origin` in browser (production: each subdomain calls its own API)
- Empty string during SSR (safety fallback)

**Never hardcode a subdomain URL in frontend code.** All API modules use `getApiBaseUrl()`. The docker-compose uses `${NEXT_PUBLIC_API_URL-default}` (single dash) so empty values in staging/production configs are respected.

### Auth0 Multi-Tenant

Each org has its own Auth0 Organization. The frontend resolves the correct org via `/api/auth/org-info` (unauthenticated, returns `auth0_org_id` from the Host header subdomain). `NEXT_PUBLIC_AUTH0_ORGANIZATION` env var is a fallback only.

### New Customer Onboarding

1. **Auth0**: Create organization, enable Username-Password + Google OAuth connections, invite users
2. **Database**: Insert org record with `auth0_org_id` + create admin user
3. **DNS**: Add A record in Squarespace for `{slug}.app.heimdex.co` → production EC2 IP
4. **SSL**: Expand Let's Encrypt cert: `sudo certbot certonly --nginx --cert-name livenow.app.heimdex.co -d livenow.app.heimdex.co -d {slug}.app.heimdex.co -d app.heimdex.co`
5. **Nginx**: Already configured for `*.app.heimdex.co` — no changes needed
6. **No web rebuild needed** — `getApiBaseUrl()` resolves dynamically

Local dev requires `/etc/hosts` entry: `127.0.0.1 devorg.app.heimdex.local`

### Google Drive Folder Sync

Watched folders support **nested subfolders** — files at any depth are discovered and ingested. The `_expand_watched_folder_ids()` helper in `discover.py` recursively enumerates subfolders via `_list_subfolders()` (BFS) and adds them to the watched set. Subfolders inherit the ancestor's `content_types` setting.

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
| `analytics-export.yml` | Daily 01:00 UTC | Export search analytics to S3 (staging + production) |
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
- `VLM_TAGS_ENABLED` — `false` by default; enables VLM-based structured tag extraction
- `AI_TAGS_ENABLED` — `false` by default; enables free-form Korean AI tags (requires `VLM_TAGS_ENABLED=true`)
- `drive_split_preset` — `default/fine/coarse/visual_only`; set per org in org settings
- `drive_stt_timeout_seconds` — timeout for STT worker callback before scene split proceeds
- `FACE_THUMBNAIL_S3_PRIMARY` — `false` by default; when `true`, face thumbnails read from S3 first with disk fallback
- `HIGHLIGHT_REEL_ENABLED` — `false` by default; enables person highlight reel auto-generation endpoints
- `ANALYTICS_ENABLED` — `true` by default; records search events to Postgres `search_events` table (partitioned by month)
- `ANALYTICS_EXPORT_ENABLED` — `false` by default; enables nightly S3 Parquet export via CLI. `true` on staging + production
- `ANALYTICS_S3_BUCKET` — defaults to `DRIVE_S3_BUCKET` if empty. Staging: `heimdex-drive-staging`, production: `livenow-media-prod`
- `VIDEO_SUMMARY_ENABLED` — `false` by default; enables AI video summary generation via OpenAI
- `OPENAI_API_KEY` — OpenAI API key for video summary generation (GitHub Secret on staging)
- `VIDEO_SUMMARY_MODEL` — `gpt-4o-mini` by default; model for summary generation

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

**Rule**: Never set `>=X.Y.Z` in pyproject.toml if that version doesn't exist on PyPI yet. The current safe floor is `>=0.8.0` (latest on PyPI: 0.8.2). To publish a new version, tag `vX.Y.Z` in the contracts repo.

## Cross-Repo Dependency: heimdex-worker-sdk

The worker SDK is installed from **PyPI** during Docker builds (`pip install "heimdex-worker-sdk==0.1.0"`). For local dev, volume-mount from `../heimdex-worker-sdk` for hot-reload.

**Rule**: Always pin `==X.Y.Z` in Dockerfiles. Never set a version that doesn't exist on PyPI. To publish a new version, tag `vX.Y.Z` in the `heimdex-worker-sdk` repo — CI auto-publishes to PyPI.

**After changing the SDK**: Update the pinned version in ALL Dockerfiles (13 files across `services/`) and verify all workers still import correctly.

## OpenSearch Scene Index Conventions

- **Doc ID format**: `{org_id}:{scene_id}` — e.g., `4d20264c-...:gd_1f7b991a_scene_037`
- **`mget_scenes(doc_ids)`**: Takes a single `list[str]` argument (NOT `org_id, scene_ids`). Returns `dict[str, dict]`.
- **`find_scene_ids_by_video_id(org_id, video_id)`**: Returns list of `scene_id` strings (not doc IDs)
- When constructing doc IDs for `mget_scenes`, always prefix: `[f"{org_id}:{sid}" for sid in scene_ids]`
- The scene search client (`get_scene_opensearch_client`) is a `SceneSearchClient` instance with `SceneIngestMixin`

### INDEX_VERSION and Alias (CRITICAL)

`SceneSearchClient.INDEX_VERSION` in `scene_client.py` **must match the promoted alias target**. Currently: `v5` (alias `heimdex_scenes` → `heimdex_scenes_v5`).

- **Reads** (search, facets) use `alias_name` → correct regardless of INDEX_VERSION
- **Writes** (bulk_index, bulk_partial_update, mget) use `index_name` → derived from `INDEX_VERSION`
- **Deletes** (delete_by_query) use `alias_name` → correct regardless

If INDEX_VERSION doesn't match the alias target, **ingested scenes become invisible** (written to old index, reads go to new index via alias). After running `promote_alias.py`, always update INDEX_VERSION to match.

## Frontend Testing

- **Test runner**: Vitest + Testing Library (`@testing-library/react`)
- **Config**: `services/web/vitest.config.ts` — `@` alias resolves to `./src`
- **CRITICAL**: Always run `npx vitest` from `services/web/`, NOT from the repo root. Running from root picks up `e2e/` Playwright files and tests without the vitest config, causing false failures.
- **Test location**: Unit tests in `features/*/` next to code, or in `src/__tests__/`
- **JSX test files**: Must have `.tsx` extension and vitest environment must be `jsdom`

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
- Changing `NEXT_PUBLIC_*` vars without rebuilding the web container (they are baked at build time)
- Hardcoding subdomain URLs (e.g., `livenow.app.heimdex.co`) in frontend code — use `getApiBaseUrl()` instead
- Using `${VAR:-default}` (colon-dash) for `NEXT_PUBLIC_API_URL` in docker-compose — must use `${VAR-default}` (single dash) so empty values are respected
- Setting `AUTH0_ENABLED=false` with `ENVIRONMENT=staging` or `production` (crashes API)
- Setting `heimdex-media-contracts>=X.Y.Z` where X.Y.Z is not on PyPI (breaks Docker build)
- Setting `heimdex-worker-sdk==X.Y.Z` in Dockerfiles where X.Y.Z is not on PyPI (breaks Docker build)
- Updating DB without updating OpenSearch (stale search results / dates)
- Google Drive incremental sync: forgetting to add new fields to the `changes().list()` fields parameter (only full scan fields auto-include everything)
- Setting `DRIVE_SPEECH_SPLIT_ENABLED=true` without the STT worker deployed (videos get stuck in `awaiting_stt`)
- Setting `AI_TAGS_ENABLED=true` without `VLM_TAGS_ENABLED=true` (ai_tags only flow through the VLM path)
- Importing from `shorts_render` internals in `highlight_reel` module (hexagonal boundary — use service interface via DI)
- Adding I/O imports (DB, OpenSearch, S3) to `highlight_reel/domain.py` (must stay pure)
- Using `value || fallback` with numeric values that can be 0 (use `value ?? fallback` or `value != null` instead — JS treats 0 as falsy)
- Using `HEAD` requests to check if API endpoints exist (many FastAPI routes only support GET/POST — use GET or skip the check)
- Passing `org_id` as first arg to `mget_scenes()` — it only takes `doc_ids: list[str]` where doc_id = `{org_id}:{scene_id}`
- Assuming `get_video_scenes()` returns a list — it returns `{"scenes": [...], "total": N}` dict. Extract `result["scenes"]` first.
- Silently swallowing exceptions with bare `except Exception: pass` in API endpoints (log at minimum with `logger.warning`)
- Running `npx vitest` from repo root instead of `services/web/` (picks up Playwright e2e files, causes false failures)
- Not adjusting `selectedClipIndex`/`selectedSubtitleIndex` when removing items before the selected index in array-based selection (off-by-one after splice)
- Using stale closures in React effects that read frequently-changing values like `playheadMs` — use refs for values that change every frame, deps arrays for values that change on user action
- Running `promote_alias.py` without updating `SceneSearchClient.INDEX_VERSION` in `scene_client.py` (writes go to old index, reads go to new — scenes become invisible)

## Documentation

- `/README.md` — Quick start, multi-tenancy invariants, API reference
- `/docs/architecture.md` — System design, search algorithm, data models
- `/docs/AUTH0_SETUP.md` — Auth0 integration guide
- `/docs/search-quality.md` — Search quality evaluation
- `/docs/SCENE_GROUPING_ARCHITECTURE.md` — Scene clustering logic
- Workspace `docs/` — See [ECOSYSTEM.md](../../docs/ECOSYSTEM.md) for full index
