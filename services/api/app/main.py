import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.logging_config import setup_logging, get_logger
from app.db import models  # noqa: F401 - Register all SQLAlchemy models
from app.modules.tenancy import TenancyMiddleware
from app.modules.auth.router import router as auth_router
from app.modules.search.router import router as search_router

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
    
    logger.info("application_starting", environment=get_settings().environment)
    
    opensearch_client = OpenSearchClient()
    app.state.opensearch_client = opensearch_client
    
    await _startup_search_checks(opensearch_client)
    
    yield
    
    logger.info("application_shutting_down")
    await opensearch_client.close()
    app.state.opensearch_client = None


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


app = FastAPI(
    title="Heimdex API",
    description="Video search and indexing platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(TenancyMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://devorg.app.heimdex.local:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    
    host = request.headers.get("host", "")
    org_slug, tenancy_error = extract_org_slug(host)
    
    return {
        "status": "ok",
        "environment": get_settings().environment,
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
app.include_router(search_router, prefix="/api")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled_exception", error=str(exc))
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )
