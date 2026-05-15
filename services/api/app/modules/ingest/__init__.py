"""
Agent scene ingestion module.

Provides the POST /api/ingest/scenes endpoint that allows the Heimdex agent
to upload scene detection results for indexing into the scenes OpenSearch index.

Auth: Pre-shared API key (Bearer token) + tenancy via Host header.

Note: Do NOT add top-level imports of FastAPI-dependent modules here.
Worker containers (STT, OCR, Caption) import app.modules.ingest.models
via app.db.models, which triggers this __init__.py. Workers do not have
fastapi installed.
"""
