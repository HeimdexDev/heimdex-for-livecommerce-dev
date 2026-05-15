"""
Agent library management router.

POST /api/libraries — idempotent get-or-create library by name within org
GET /api/libraries — list all libraries for the org

Auth: Pre-shared API key (Bearer token) — no user JWT required.
Tenancy: org_id derived from Host header via TenancyMiddleware.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db_session, get_library_repository
from app.logging_config import get_logger
from app.modules.ingest.auth import verify_agent_token
from app.modules.libraries.repository import LibraryRepository
from app.modules.libraries.schemas import (
    CreateLibraryRequest,
    LibraryListResponse,
    LibraryResponse,
)
from app.modules.tenancy.context import OrgContext

logger = get_logger(__name__)

router = APIRouter(prefix="/libraries", tags=["libraries"])


@router.post("", response_model=LibraryResponse)
async def create_or_get_library(
    request: CreateLibraryRequest,
    org_ctx: OrgContext = Depends(verify_agent_token),
    library_repo: LibraryRepository = Depends(get_library_repository),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Get or create a library by name within the org (idempotent).

    If a library with the same name already exists in the org, returns it
    with created=False. Otherwise, creates a new library and returns it
    with created=True.

    Auth: Bearer token (pre-shared agent API key).
    Tenancy: org_id from Host header.

    Returns:
        LibraryResponse with id, name, and created flag.

    Raises:
        401: If Bearer token is invalid.
        403: If ingestion is disabled.
    """
    # Check if library already exists
    existing = await library_repo.get_by_name(org_ctx.org_id, request.name)
    if existing:
        logger.debug(
            "library_already_exists",
            org_id=str(org_ctx.org_id),
            library_id=str(existing.id),
            name=request.name,
        )
        return LibraryResponse(id=existing.id, name=existing.name, created=False)

    # Create new library
    library = await library_repo.create(org_ctx.org_id, request.name)
    await db.commit()

    logger.info(
        "library_created",
        org_id=str(org_ctx.org_id),
        library_id=str(library.id),
        name=request.name,
    )
    return LibraryResponse(id=library.id, name=library.name, created=True)


@router.get("", response_model=LibraryListResponse)
async def list_libraries(
    org_ctx: OrgContext = Depends(verify_agent_token),
    library_repo: LibraryRepository = Depends(get_library_repository),
):
    """
    List all libraries for the org.

    Auth: Bearer token (pre-shared agent API key).
    Tenancy: org_id from Host header.

    Returns:
        LibraryListResponse with list of libraries.

    Raises:
        401: If Bearer token is invalid.
        403: If ingestion is disabled.
    """
    libraries = await library_repo.list_by_org(org_ctx.org_id)

    logger.debug(
        "libraries_listed",
        org_id=str(org_ctx.org_id),
        count=len(libraries),
    )

    library_responses = [
        LibraryResponse(id=lib.id, name=lib.name, created=False) for lib in libraries
    ]
    return LibraryListResponse(libraries=library_responses)
