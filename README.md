# Heimdex
 
Video search platform with hybrid lexical + semantic search, supporting Korean language.

## Quick Start

### Prerequisites

- Docker and Docker Compose
- 4GB+ RAM available for containers

### REQUIRED: Add Local DNS Entry

**This step is mandatory.** Heimdex uses strict subdomain-based multi-tenancy.

```bash
# Add to /etc/hosts (requires sudo)
echo "127.0.0.1 devorg.app.heimdex.local" | sudo tee -a /etc/hosts
```

**Why is this required?** See [Multi-Tenancy Architecture](#multi-tenancy-architecture) below.

### Start Everything

```bash
# Start all services (API, Web, Postgres, OpenSearch, MinIO)
docker compose up --build

# Wait for services to be healthy (check with)
docker compose ps

# In a separate terminal, run database migrations and seed data
docker compose exec api alembic upgrade head
docker compose exec api python -m app.seed
```

### Access the Application

- **Web UI**: http://localhost:3000
- **API Health**: http://devorg.app.heimdex.local:8000/health
- **API Docs**: http://devorg.app.heimdex.local:8000/docs

> **Note**: The API must be accessed via the org subdomain (e.g., `devorg.app.heimdex.local`), 
> not `localhost`. Requests to `localhost:8000` will be rejected by design.

### Test Search

1. Open http://localhost:3000
2. Enter a search query (try Korean: "회의", "프로젝트", "보안")
3. Adjust the alpha slider:
   - **Exact** (alpha=0): Pure keyword matching (BM25)
   - **Balanced** (alpha=0.5): Mix of keyword and semantic
   - **Meaning** (alpha=1): Pure semantic/vector search
4. Enable "Debug Mode" to see ranking scores

### Reset Everything

```bash
docker compose down -v
```

## Architecture

```
heimdex/
├── services/
│   ├── api/          # FastAPI backend (Python 3.11)
│   │   └── app/
│   │       ├── modules/
│   │       │   ├── tenancy/    # Subdomain → org routing
│   │       │   ├── auth/       # Dev JWT auth (OAuth later)
│   │       │   ├── orgs/       # Organization management
│   │       │   ├── users/      # User management
│   │       │   ├── libraries/  # Video libraries
│   │       │   ├── profiles/   # Library versioning
│   │       │   ├── search/     # Hybrid search + fusion
│   │       │   ├── people/     # Face clusters + drive nicknames
│   │       │   └── artifacts/  # Asset storage (stub)
│   │       └── db/
│   │           └── migrations/
│   └── web/          # Next.js frontend (TypeScript)
├── docker-compose.yml
└── docs/
    └── architecture.md
```

### Key Components

- **Tenancy**: Routes `{org}.app.heimdex.local` → org context
- **Search**: Hybrid retrieval (BM25 + kNN) with RRF fusion
- **Diversification**: Limits results per video to prevent dominance

## Multi-Tenancy Architecture

Heimdex uses **strict subdomain-based multi-tenancy**. This is a core security invariant.

### How It Works

```
Browser → http://devorg.app.heimdex.local:8000/api/search
                    ↓
          Host header: devorg.app.heimdex.local
                    ↓
          Tenancy middleware extracts "devorg" from subdomain
                    ↓
          All queries scoped to org_id of "devorg"
```

### Why This Matters

1. **Security**: Organization ID is derived ONLY from the Host header, never from user input.
   This prevents accidental or malicious cross-org data leakage.

2. **Production Parity**: Local development behaves exactly like production.
   No "localhost magic" that could mask tenancy bugs.

3. **Explicit Boundaries**: Every API request clearly identifies its org context.
   No ambiguity about which tenant's data is being accessed.

### Invariants (Never Violate)

| Rule | Rationale |
|------|-----------|
| org_id from Host header ONLY | Prevents client-side manipulation |
| No localhost fallbacks | Keeps dev behavior aligned with prod |
| Reject invalid hosts explicitly | Fail loud, not silent |

### Local Development Setup

The `/etc/hosts` entry maps the org subdomain to localhost:

```
127.0.0.1 devorg.app.heimdex.local
```

The web container uses `extra_hosts: host-gateway` to route API calls through the host machine.

### Verifying Tenancy

Check the `/health` endpoint to see resolved tenancy:

```bash
curl http://devorg.app.heimdex.local:8000/health | jq
```

Response includes:
```json
{
  "status": "ok",
  "tenancy": {
    "host": "devorg.app.heimdex.local:8000",
    "org_slug": "devorg",
    "error": null
  }
}
```

If you see `"error": "localhost"` or `"org_slug": null`, your setup is incorrect.

## API Reference

### Search Endpoint

```bash
POST /api/search
Host: devorg.app.heimdex.local

{
  "q": "search query",
  "alpha": 0.5,
  "filters": {
    "source_types": ["gdrive", "removable_disk"],
    "library_ids": ["uuid"],
    "person_cluster_ids": ["cluster_id"],
    "date_from": "2024-01-01T00:00:00Z",
    "date_to": "2024-12-31T23:59:59Z"
  }
}
```

### Dev Login (Development Only)

```bash
POST /api/auth/dev-login
Host: devorg.app.heimdex.local

{
  "email": "admin@devorg.example.com"
}
```

Returns JWT token for authenticated endpoints.

## Development

### Run Tests

```bash
# Inside API container
docker compose exec api pytest

# Or locally with dependencies
cd services/api
pip install -e ".[dev]"
pytest
```

### Run Linting

```bash
docker compose exec api ruff check app/
docker compose exec api mypy app/
```

### Database Migrations

```bash
# Create new migration
docker compose exec api alembic revision --autogenerate -m "description"

# Apply migrations
docker compose exec api alembic upgrade head

# Rollback
docker compose exec api alembic downgrade -1
```

## Configuration

### Environment Variables (API)

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://...` | Async Postgres connection |
| `OPENSEARCH_URL` | `http://opensearch:9200` | OpenSearch endpoint |
| `JWT_SECRET_KEY` | `dev-secret...` | JWT signing key |
| `EMBEDDING_DIMENSION` | `1024` | Vector embedding size (multilingual-e5-large) |
| `SEARCH_LEXICAL_TOP_K` | `200` | Lexical candidate pool size |
| `SEARCH_VECTOR_TOP_K` | `200` | Vector candidate pool size |
| `SEARCH_RRF_K` | `60` | RRF ranking constant |
| `SEARCH_MAX_SCENES_PER_VIDEO` | `4` | Diversification cap |

### Environment Variables (Web)

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_API_URL` | `http://devorg.app.heimdex.local:8000` | API endpoint (must use org subdomain) |
| `NEXT_PUBLIC_AUTH0_ENABLED` | `false` | Enable Auth0 authentication |
| `NEXT_PUBLIC_AUTH0_DOMAIN` | - | Auth0 tenant domain |
| `NEXT_PUBLIC_AUTH0_CLIENT_ID` | - | Auth0 SPA client ID |
| `NEXT_PUBLIC_AUTH0_AUDIENCE` | - | Auth0 API audience identifier |

## Authentication

Heimdex supports two authentication modes:

### Development Mode (Default)

When `AUTH0_ENABLED=false` (default), Heimdex uses a simple dev-login flow:

1. Click "Dev Login" in the header
2. Enter an email that exists in the database (e.g., `admin@devorg.example.com`)
3. The API issues a JWT token stored in sessionStorage

This mode is convenient for local development but NOT suitable for production.

### Auth0 Mode (Production)

For production, enable Auth0 authentication:

#### 1. Create Auth0 Application

1. Go to [Auth0 Dashboard](https://manage.auth0.com/)
2. Create a new **Single Page Application**
3. Configure these settings:
   - **Allowed Callback URLs**: `http://localhost:3000/callback`, `https://your-domain.com/callback`
   - **Allowed Logout URLs**: `http://localhost:3000`, `https://your-domain.com`
   - **Allowed Web Origins**: `http://localhost:3000`, `https://your-domain.com`

#### 2. Create Auth0 API

1. In Auth0 Dashboard, go to **Applications > APIs**
2. Create a new API with identifier: `https://api.heimdex.io` (or your custom identifier)
3. Enable **RBAC** if you need role-based permissions

#### 3. Configure Environment Variables

**API (services/api or docker-compose.yml):**
```bash
AUTH0_ENABLED=true
AUTH0_DOMAIN=your-tenant.auth0.com
AUTH0_AUDIENCE=https://api.heimdex.io
AUTH0_ORG_CLAIM=https://heimdex.io/org_id
```

**Web (services/web or docker-compose.yml):**
```bash
NEXT_PUBLIC_AUTH0_ENABLED=true
NEXT_PUBLIC_AUTH0_DOMAIN=your-tenant.auth0.com
NEXT_PUBLIC_AUTH0_CLIENT_ID=your-spa-client-id
NEXT_PUBLIC_AUTH0_AUDIENCE=https://api.heimdex.io
```

#### 4. (Optional) Configure Organization Claim

If using Auth0 Organizations:

1. Enable Organizations in Auth0 Dashboard
2. Add a custom claim to include org_id in tokens via Auth0 Actions:
   ```javascript
   exports.onExecutePostLogin = async (event, api) => {
     if (event.organization) {
       api.accessToken.setCustomClaim(
         'https://heimdex.io/org_id',
         event.organization.name
       );
     }
   };
   ```

**Note**: Even with Auth0, tenancy is ALWAYS derived from the Host header subdomain. The org claim is for additional validation, not primary routing.

## Troubleshooting

### OpenSearch won't start

Increase Docker memory limit or add to `~/.docker/daemon.json`:
```json
{
  "memory": 4096
}
```

### Embeddings: First Run Model Download

On first run with `EMBEDDING_USE_MOCK=false`, the API downloads the embedding model from HuggingFace:
- **Model**: `intfloat/multilingual-e5-large` (~2.4GB)
- **Download time**: 2-10 minutes depending on network speed
- **Cache location**: `huggingface_cache` Docker volume

**Skip download for development:**
```bash
# In docker-compose.yml, EMBEDDING_USE_MOCK=true is the default
# This uses deterministic mock embeddings (no download needed)
```

**Force real embeddings:**
```bash
# Edit docker-compose.yml:
- EMBEDDING_USE_MOCK=false

# Or override at runtime:
docker compose exec api env EMBEDDING_USE_MOCK=false python -m app.seed
```

**Cache persistence:**
The `huggingface_cache` volume persists the model between container rebuilds.
To clear and re-download:
```bash
docker volume rm heimdex_huggingface_cache
```

### Index Migration (Schema Changes)

When you need to change the OpenSearch index schema (e.g., new fields, different embedding dimension):

```bash
# 1. Bump INDEX_VERSION in services/api/app/modules/search/client.py
#    Edit: INDEX_VERSION = "v3"  # was "v2"

# 2. Rebuild and deploy
docker compose up --build -d api

# 3. Seed data into new index
docker compose exec api python -m app.seed

# 4. Promote alias to new index (atomic swap)
docker compose exec api python -m app.modules.search.promote_alias

# 5. Verify migration
docker compose exec api python -c "
import asyncio
from app.modules.search.client import OpenSearchClient
async def check():
    c = OpenSearchClient()
    print(await c.get_index_info())
    await c.close()
asyncio.run(check())
"
```

**Expected promote_alias output:**
```
============================================================
OpenSearch Alias Promotion Tool
============================================================

Target index: heimdex_segments_v3
Target alias: heimdex_segments

Step 1: Checking index state...
  - Index already exists: heimdex_segments_v3
  - WARNING: ALIAS MISMATCH DETECTED...

Step 2: Getting current alias state...
  - Current alias targets: ['heimdex_segments_v2']
  - Alias mismatch: True

Step 3: Promoting alias to current version...
  - Before: ['heimdex_segments_v2']
  - After: ['heimdex_segments_v3']

Step 4: Verifying promotion...
  - Alias targets: ['heimdex_segments_v3']
  - Points to current: True

============================================================
SUCCESS: Alias promotion completed successfully!
============================================================
```

### Alias Mismatch Warning

If you see this warning during startup:
```
ALIAS MISMATCH DETECTED: Alias 'heimdex_segments' exists but points to 
['heimdex_segments_v1'], not 'heimdex_segments_v2'.
```

This means the code version expects a newer index but the alias still points to an older one.

**Fix:**
```bash
# Ensure new index has data
docker compose exec api python -m app.seed

# Promote alias
docker compose exec api python -m app.modules.search.promote_alias
```

### Korean search not working well

The current setup uses Nori analyzer when the plugin is available. If Korean search quality is poor:
1. Verify Nori plugin: `docker compose exec opensearch bin/opensearch-plugin list`
2. Check logs for `"nori_available": true` during index creation
3. Re-create index if needed: delete and re-seed

### Org not found error / Tenancy errors

**Symptom**: API returns 400 with "Multi-tenancy requires org subdomain" or similar.

**Cause**: Missing `/etc/hosts` entry or calling API via `localhost`.

**Fix**:
```bash
# 1. Add hosts entry
echo "127.0.0.1 devorg.app.heimdex.local" | sudo tee -a /etc/hosts

# 2. Verify it works
curl http://devorg.app.heimdex.local:8000/health | jq .tenancy

# Expected: { "org_slug": "devorg", "error": null }
# Wrong:    { "org_slug": null, "error": "localhost" }
```

**Remember**: The API MUST be accessed via the org subdomain, not localhost. This is by design.

## Roadmap

- [x] Auth0 OAuth integration (SPA + API)
- [x] Production embedding model (multilingual-e5-large, 1024-dim)
- [ ] Nori analyzer for Korean text
- [ ] Local agent for video playback
- [ ] Cloud GPU worker for heavy compute
- [ ] Real-time indexing pipeline
