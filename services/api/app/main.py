import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.logging_config import setup_logging, get_logger
from app.db import models  # noqa: F401 - Register all SQLAlchemy models
from app.modules.tenancy import TenancyMiddleware
from app.modules.auth.router import router as auth_router
from app.modules.agent_intents.router import router as agent_intents_router
from app.modules.agent_intents.schema_check import startup_check_agent_intents_schema
from app.modules.devices.router import router as devices_router
from app.modules.ingest.router import router as ingest_router
from app.modules.libraries.router import router as libraries_router
from app.modules.people.router import router as people_router
from app.modules.search.router import router as search_router
from app.modules.videos.router import router as videos_router

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    
    Startup:
    - Creates OpenSearch client and stores in app.state
    - Runs infrastructure checks (Nori analyzer, index/alias)
    
    Shutdown:
    - Closes OpenSearch client
    """
    from app.modules.search.client import OpenSearchClient
    from app.modules.search.scene_client import SceneSearchClient
    
    settings = get_settings()
    logger.info("application_starting", environment=settings.environment)
    settings.validate_production_guards()
    
    from app.db.base import get_async_engine

    startup_engine = get_async_engine()
    if settings.auth0_enabled:
        await _verify_org_auth0_bindings(startup_engine)
    await startup_check_agent_intents_schema(startup_engine, settings.agent_intents_enabled)
    await startup_engine.dispose()

    opensearch_client = OpenSearchClient()
    app.state.opensearch_client = opensearch_client
    
    scene_opensearch_client = SceneSearchClient()
    app.state.scene_opensearch_client = scene_opensearch_client
    
    await _startup_search_checks(opensearch_client)
    await _startup_scene_search_checks(scene_opensearch_client)

    if settings.embedding_use_mock:
        logger.warning(
            "embedding_mock_mode_active",
            message="EMBEDDING_USE_MOCK=true — semantic search is disabled. "
                    "All embeddings are deterministic hashes. "
                    "Search accuracy benchmarks will be INVALID.",
            embedding_model=settings.embedding_model,
            embedding_dimension=settings.embedding_dimension,
            impact="search_accuracy_invalid",
        )
    
    yield
    
    logger.info("application_shutting_down")
    await opensearch_client.close()
    await scene_opensearch_client.close()
    app.state.opensearch_client = None
    app.state.scene_opensearch_client = None


async def _startup_search_checks(client):
    """
    Run startup checks for OpenSearch infrastructure.
    
    Checks:
    1. Nori analyzer availability (warns if missing)
    2. Index exists and alias state (warns on mismatch)
    """
    try:
        nori_available = await client._check_nori_available()
        if not nori_available:
            logger.warning(
                "nori_analyzer_not_available",
                message="Korean analyzer (Nori) is NOT installed. "
                        "Korean search quality will be degraded. "
                        "Install with: bin/opensearch-plugin install analysis-nori",
                impact="korean_search_quality_degraded",
            )
        else:
            logger.info("nori_analyzer_available", status="ok")
        
        result = await client.ensure_index_exists()
        
        if result.get("alias_mismatch_warning"):
            logger.warning(
                "startup_alias_mismatch",
                warning=result["alias_mismatch_warning"],
                current_targets=result.get("alias_current_targets"),
                intended_index=client.index_name,
                action="Run 'python -m app.modules.search.promote_alias' to fix",
            )
        else:
            logger.info(
                "search_infrastructure_ready",
                index=client.index_name,
                alias=client.alias_name,
            )
        
    except Exception as e:
        logger.error(
            "startup_search_check_failed",
            error=str(e),
            message="Search infrastructure check failed. Search may not work correctly.",
        )


async def _startup_scene_search_checks(client):
    """
    Run startup checks for the scene OpenSearch index.
    
    Creates the scene index if missing and warns on alias mismatch.
    """
    try:
        result = await client.ensure_index_exists()
        
        if result.get("alias_mismatch_warning"):
            logger.warning(
                "startup_scene_alias_mismatch",
                warning=result["alias_mismatch_warning"],
                current_targets=result.get("alias_current_targets"),
                intended_index=client.index_name,
                action="Run promote_alias_to_current_version() to fix",
            )
        else:
            logger.info(
                "scene_search_infrastructure_ready",
                index=client.index_name,
                alias=client.alias_name,
            )
        
    except Exception as e:
        logger.error(
            "startup_scene_search_check_failed",
            error=str(e),
            message="Scene search infrastructure check failed. Scene search may not work.",
        )


async def _verify_org_auth0_bindings(engine) -> None:
    """Fail-closed check: every org must have auth0_org_id when Auth0 is enabled.

    Prevents the app from serving requests to orgs that cannot be
    validated against Auth0 Organizations tokens.
    """
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        result = await session.execute(
            text("SELECT slug FROM orgs WHERE auth0_org_id IS NULL")
        )
        unbound = [row[0] for row in result.fetchall()]

    if not unbound:
        logger.info("org_auth0_bindings_verified")
        return

    msg = (
        f"\n{'='*60}\n"
        f"FATAL: AUTH0_ENABLED=true but {len(unbound)} org(s) have no auth0_org_id:\n\n"
        + "\n".join(f"  - {slug}" for slug in unbound)
        + "\n\nEvery org must be bound to an Auth0 Organization.\n"
        f"Run: UPDATE orgs SET auth0_org_id = '<org_id>' WHERE slug = '<slug>';\n"
        f"{'='*60}"
    )
    logger.critical("org_auth0_binding_missing", unbound_orgs=unbound)
    raise SystemExit(msg)


app = FastAPI(
    title="Heimdex API",
    description="Video search and indexing platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(TenancyMiddleware)

_settings = get_settings()
_extra = [o.strip() for o in _settings.cors_extra_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_extra or [],
    allow_origin_regex=_settings.cors_allow_origin_regex,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Heimdex-Request-Id",
        "X-Heimdex-Device-Id",
        "X-Heimdex-Timestamp",
        "X-Heimdex-Idempotency-Key",
    ],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def add_request_context(request: Request, call_next):
    request_id = str(uuid.uuid4())
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/health")
async def health(request: Request):
    from app.modules.tenancy.middleware import extract_org_slug

    settings = get_settings()
    embedding_mode = "mock" if settings.embedding_use_mock else "real"
    if embedding_mode == "mock":
        logger.warning("embedding_mock_mode_active")

    host = request.headers.get("host", "")
    org_slug, tenancy_error = extract_org_slug(host)

    return {
        "status": "ok",
        "environment": settings.environment,
        "embedding_mode": embedding_mode,
        "tenancy": {
            "host": host,
            "org_slug": org_slug,
            "error": tenancy_error,
        },
    }


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    return {"status": "ok"}


app.include_router(auth_router, prefix="/api")
app.include_router(devices_router, prefix="/api")
app.include_router(agent_intents_router, prefix="/api")
app.include_router(ingest_router, prefix="/api")
app.include_router(libraries_router, prefix="/api")
app.include_router(people_router, prefix="/api")
app.include_router(search_router, prefix="/api")
app.include_router(videos_router, prefix="/api")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled_exception", error=str(exc))
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )
