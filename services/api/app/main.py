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
from app.modules.subtitle_presets.router import router as subtitle_presets_router
from app.modules.shorts_auto.router import router as shorts_auto_router
from app.modules.shorts_auto_product.router import (
    router as shorts_auto_product_router,
)
from app.modules.shorts_auto_product.internal_router import (
    router as internal_shorts_auto_product_router,
)
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
from app.modules.worker_events.recorder import record_worker_event

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
    record_worker_event(
        service="api",
        event_name="application_starting",
        category="healthcheck",
        level="INFO",
        metadata={"environment": settings.environment},
    )
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
    await _ensure_worker_event_partitions(engine)
    # Closed-vocab sidecar reachability probe. Logs ERROR (not raises) if
    # the flag is on but the service is unreachable — without this the
    # only signal is a per-query WARNING that's easy to miss in noise.
    # See feedback_external_lib_eager_init_fail_loud.md memory + the
    # silent-fail-open pattern tracked in pr-patterns.json.
    await _startup_closed_vocab_check(settings)

    # Phase 4 wizard child runner — picks up queued ``mode='render_child'``
    # rows produced by the parent fan-out hook in
    # ``shorts_auto_product.internal_router.complete``. One runner per
    # API replica; DB-atomic claim resolves the race across replicas.
    # Real picker + render-service integration shipped in PR #6
    # (``children/runner.py::_process_child_payload``).
    from app.db.base import get_async_session_factory
    from app.modules.shorts_auto_product.children import create_child_runner

    child_runner = create_child_runner(
        settings=settings,
        session_factory=get_async_session_factory(),
        # ``ShortsRenderService`` (constructed inside the runner per
        # render call) needs the scene OS client to validate
        # scene_clip boundaries before persisting the render job.
        # Set on app.state above; reused here so the runner doesn't
        # have to re-read settings or open its own OS connection.
        scene_search_client=app.state.scene_opensearch_client,
    )
    child_runner.start()
    app.state.product_v2_child_runner = child_runner

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
    record_worker_event(
        service="api",
        event_name="application_shutting_down",
        category="healthcheck",
        level="INFO",
    )
    await opensearch_client.close()
    await scene_opensearch_client.close()
    app.state.opensearch_client = None
    app.state.scene_opensearch_client = None

    # Drain the wizard child runner before disposing the engine.
    # In-flight children get up to 30s to /complete; tasks still
    # running after the timeout are cancelled and the lease will
    # expire so another replica re-claims on its next poll.
    runner = getattr(app.state, "product_v2_child_runner", None)
    if runner is not None:
        await runner.stop(drain_timeout_seconds=30.0)
        app.state.product_v2_child_runner = None

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


async def _startup_closed_vocab_check(settings) -> None:
    """
    Probe the closed-vocab-search sidecar's /health on boot.

    Runs only when ``CLOSED_VOCAB_ENABLED=true``. Logs ``ERROR`` if the
    service is unreachable so operators see the issue at startup rather
    than discovering it post-deploy via degraded search and a per-query
    ``closed_vocab_service_error`` WARNING that's easy to miss.

    Does NOT raise. ``ClosedVocabClient.classify`` is intentionally
    fail-open — if the sidecar is down, semantic search continues to
    work via the pure pipeline. The loud startup signal exists so
    that "search degraded" incidents have a single clear breadcrumb.
    """
    if not settings.closed_vocab_enabled:
        return
    base_url = settings.closed_vocab_service_url
    if not base_url:
        logger.error(
            "closed_vocab_startup_misconfigured",
            message="CLOSED_VOCAB_ENABLED=true but CLOSED_VOCAB_SERVICE_URL is empty. "
                    "Every classify() call will short-circuit to None and search "
                    "will silently fall through to the pure pipeline.",
        )
        return
    try:
        import httpx

        timeout = httpx.Timeout(settings.closed_vocab_timeout_ms / 1000)
        async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
            response = await client.get("/health")
            response.raise_for_status()
            payload = response.json() if response.content else {}
            logger.info(
                "closed_vocab_startup_ok",
                base_url=base_url,
                vocab_size=payload.get("vocab_size"),
                status=payload.get("status"),
            )
    except Exception as exc:
        logger.error(
            "closed_vocab_startup_unreachable",
            base_url=base_url,
            error=str(exc),
            message="Sidecar is unreachable but CLOSED_VOCAB_ENABLED=true. "
                    "Search will silently fall through to the pure pipeline "
                    "and per-query WARNING logs will accumulate.",
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


async def _ensure_worker_event_partitions(engine) -> None:
    """Create worker_events partitions for the current and next 2 months.

    Uses a short-lived session independent of the request lifecycle.
    Safe to call on every startup — all DDL is IF NOT EXISTS.
    """
    from app.modules.worker_events.repository import WorkerEventRepository

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            repo = WorkerEventRepository(session)
            partitions = await repo.ensure_partitions(months_ahead=2)
            await session.commit()
            logger.info("worker_event_partitions_ready", partitions=partitions)
    except Exception as e:
        logger.warning(
            "worker_event_partition_setup_failed",
            error=str(e),
            message="Worker observability writes will fail until partitions are created. "
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
app.include_router(subtitle_presets_router, prefix="/api")
app.include_router(shorts_auto_router, prefix="/api")
# shorts-auto product mode v2 — public + internal worker callbacks.
# Behind ``auto_shorts_product_v2_enabled`` feature flag at the
# service layer; until that flips, every endpoint 404s with
# "product mode v2 is not enabled" so the v1 product mode UI stays
# unchanged.
app.include_router(shorts_auto_product_router, prefix="/api")
app.include_router(internal_shorts_auto_product_router)
app.include_router(text_templates_router, prefix="/api")

from app.modules.shorts_render.internal_router import router as internal_shorts_render_router
app.include_router(internal_shorts_render_router)

app.include_router(blur_router, prefix="/api")
from app.modules.blur.internal_router import router as internal_blur_router
app.include_router(internal_blur_router)
from app.modules.blur.export_internal_router import router as internal_blur_export_router
app.include_router(internal_blur_export_router)

from app.modules.worker_events.internal_router import router as internal_worker_events_router
app.include_router(internal_worker_events_router)

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
    record_worker_event(
        service="api",
        event_name="unhandled_exception",
        category="system_error",
        level="ERROR",
        message=str(exc)[:1000],
        metadata={
            "path": request.url.path,
            "method": request.method,
            "exception_type": type(exc).__name__,
        },
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )
