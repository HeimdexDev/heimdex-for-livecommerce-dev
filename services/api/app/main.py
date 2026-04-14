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
from app.modules.orgs.router import router as org_settings_router
from app.modules.highlight_reel.router import router as highlight_reel_router
from app.modules.people.router import router as people_router
from app.modules.search.router import router as search_router
from app.modules.shorts.router import router as shorts_router
from app.modules.shorts_render.router import router as shorts_render_router
from app.modules.blur.router import router as blur_router
from app.modules.text_templates.router import router as text_templates_router
from app.modules.basket.router import router as basket_router
from app.modules.thumbnails.router import public_router as thumbnails_public_router
from app.modules.thumbnails.router import upload_router as thumbnails_upload_router
from app.modules.videos.router import router as videos_router
from app.modules.videos.internal_router import router as videos_internal_router
from app.modules.scene_overrides.router import router as scene_overrides_router
from app.modules.grouping.router import router as grouping_router
from app.modules.video_summary.router import router as video_summary_router
from app.modules.youtube.router import router as youtube_router

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

    engine = get_async_engine()
    if settings.auth0_enabled:
        await _verify_org_auth0_bindings(engine)
    await startup_check_agent_intents_schema(engine, settings.agent_intents_enabled)

    opensearch_client = OpenSearchClient()
    app.state.opensearch_client = opensearch_client
    
    scene_opensearch_client = SceneSearchClient()
    app.state.scene_opensearch_client = scene_opensearch_client
    
    await _startup_search_checks(opensearch_client)
    await _startup_scene_search_checks(scene_opensearch_client)
    await _ensure_search_event_partitions(engine)

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

    await engine.dispose()

    from app.modules.auth.oidc import close_http_client
    close_http_client()


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


async def _ensure_search_event_partitions(engine) -> None:
    """Create search_events partitions for the current and next 2 months.

    Uses a short-lived session independent of the request lifecycle.
    Safe to call on every startup — all DDL is IF NOT EXISTS.
    """
    from app.modules.search.search_event_repository import SearchEventRepository

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            repo = SearchEventRepository(session)
            partitions = await repo.ensure_partitions(months_ahead=2)
            await session.commit()
            logger.info("search_event_partitions_ready", partitions=partitions)
    except Exception as e:
        logger.warning(
            "search_event_partition_setup_failed",
            error=str(e),
            message="Search analytics will fail until partitions are created. "
                    "This is non-fatal — the API will start normally.",
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

# Environment-aware CORS: development allows http://, localhost, *.heimdex.local;
# staging/production restricts to HTTPS-only on known production domains.
if _settings.environment == "development":
    _cors_origin_regex = _settings.cors_allow_origin_regex
else:
    _cors_origin_regex = (
        r"^https://"
        r"[a-z0-9][a-z0-9-]{0,}[a-z0-9]\.app\.(?:heimdex\.co|heimdexdemo\.dev)$"
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_extra or [],
    allow_origin_regex=_cors_origin_regex,
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
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if _settings.environment != "development":
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
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
app.include_router(thumbnails_upload_router, prefix="/api")
app.include_router(libraries_router, prefix="/api")
app.include_router(org_settings_router, prefix="/api")
app.include_router(people_router, prefix="/api")
app.include_router(highlight_reel_router, prefix="/api/people/{person_cluster_id}/highlight-reel")
app.include_router(search_router, prefix="/api")
app.include_router(shorts_router, prefix="/api")
app.include_router(shorts_render_router, prefix="/api")
app.include_router(text_templates_router, prefix="/api")

from app.modules.shorts_render.internal_router import router as internal_shorts_render_router
app.include_router(internal_shorts_render_router)

app.include_router(blur_router, prefix="/api")
from app.modules.blur.internal_router import router as internal_blur_router
app.include_router(internal_blur_router)
from app.modules.blur.export_internal_router import router as internal_blur_export_router
app.include_router(internal_blur_export_router)

app.include_router(basket_router, prefix="/api")
app.include_router(thumbnails_public_router, prefix="/api")
app.include_router(videos_router, prefix="/api")
app.include_router(scene_overrides_router, prefix="/api")
app.include_router(grouping_router, prefix="/api")
app.include_router(video_summary_router, prefix="/api")

if get_settings().youtube_enabled:
    app.include_router(youtube_router, prefix="/api")

    from app.modules.youtube.internal_router import router as internal_youtube_router

    app.include_router(internal_youtube_router)

if get_settings().drive_connector_enabled:
    from app.modules.drive.router import router as drive_router
    from app.modules.drive.router import playback_router
    from app.modules.drive.oauth_router import oauth_router as drive_oauth_router
    from app.modules.export.router import router as export_router
    app.include_router(drive_router, prefix="/api")
    if get_settings().folder_sync_v2_enabled:
        from app.modules.drive.watched_folder_router import router as watched_folder_router
        app.include_router(watched_folder_router, prefix="/api")
    app.include_router(drive_oauth_router, prefix="/api")
    app.include_router(playback_router, prefix="/api")
    app.include_router(export_router, prefix="/api")

    from app.modules.ingest.internal_router import router as internal_ingest_router
    app.include_router(internal_ingest_router)

    from app.modules.drive.internal_router import router as internal_drive_router
    app.include_router(internal_drive_router)

    from app.modules.drive.internal_sync_router import router as internal_drive_sync_router
    app.include_router(internal_drive_sync_router)

    from app.modules.drive.internal_processing_router import router as internal_drive_processing_router
    app.include_router(internal_drive_processing_router)

    from app.modules.face.router import router as internal_face_router
    app.include_router(internal_face_router)

    from app.modules.export.internal_router import router as internal_export_router
    app.include_router(internal_export_router)

    app.include_router(videos_internal_router, prefix="/internal")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled_exception", error=str(exc))
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )
