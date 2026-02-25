# Heimdex API

FastAPI backend for the Heimdex video search platform.

## Development

```bash
# Install dependencies
pip install -e ".[dev]"

# Run server
uvicorn app.main:app --reload

# Run tests
pytest

# Lint
ruff check app/
```

## Modules

- `tenancy` - Subdomain → org routing
- `auth` - JWT authentication (dev mode)
- `orgs` - Organization management
- `users` - User management
- `libraries` - Video library management
- `profiles` - Library versioning
- `search` - Hybrid search (BM25 + kNN) with dual-index support (segments + scenes)
- `people` - Face clusters, drive nicknames
- `artifacts` - Asset storage (stub)

## Search Modes

The API supports two search modes controlled by `SEARCH_DEFAULT_MODE`:

| Mode | Value | `POST /api/search` | `POST /api/search/scenes` |
|------|-------|---------------------|---------------------------|
| Segments | `segments` (default) | Segment results | Scene results |
| Scenes | `scenes` | Scene results | Scene results |

Rollback: set `SEARCH_DEFAULT_MODE=segments` and restart.

## Search Quality Feature Flags

These flags control search quality improvements. All default to safe/off values.

| Env Var | Default | Effect |
|---------|---------|--------|
| `SEARCH_TITLE_BOOST_ENABLED` | `false` | Enable `video_title_text` boost in lexical queries |
| `SEARCH_TITLE_BOOST` | `3.0` | Boost weight for title matches |
| `SEARCH_TAG_BOOST_ENABLED` | `false` | Enable tag-based term boost |
| `SEARCH_TAG_BOOST` | `2.0` | Boost weight for tag matches |
| `SEARCH_RRF_K` | `20` | RRF fusion constant (was 60) |

Enable all improvements:

```bash
SEARCH_TITLE_BOOST_ENABLED=true SEARCH_TAG_BOOST_ENABLED=true SEARCH_RRF_K=20
```

Rollback:

```bash
SEARCH_TITLE_BOOST_ENABLED=false SEARCH_TAG_BOOST_ENABLED=false SEARCH_RRF_K=60
```

Prerequisites: run `scripts/backfill_title_text.py` before enabling title boost.
Full runbook: `docs/SEARCH_QUALITY_ROLLOUT_RUNBOOK.md`.
