"""
Centralized dependency injection providers for Heimdex API.

All FastAPI route dependencies should be imported from this module.

DI Pattern:
- Long-lived resources (OpenSearch client) are created at app startup via lifespan
- Resources are stored in app.state for access via Request
- Services are created per-request via dependency factories
"""
from typing import AsyncGenerator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db_session as _get_db_session


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Database session dependency."""
    async for session in _get_db_session():
        yield session


def get_opensearch_client(request: Request):
    """
    OpenSearch client dependency (segments index).
    
    Client is created at app startup and stored in app.state.
    See main.py lifespan for initialization.
    """
    return request.app.state.opensearch_client


def get_scene_opensearch_client(request: Request):
    """
    Scene OpenSearch client dependency (scenes index).
    
    Client is created at app startup and stored in app.state.
    See main.py lifespan for initialization.
    """
    return request.app.state.scene_opensearch_client


def get_embedding_service():
    """
    Embedding service dependency.
    
    Returns singleton embedding service (cached via lru_cache in module).
    """
    from app.modules.search.embedding import get_embedding_service as _get_embedding_service
    return _get_embedding_service()


def get_user_repository(db: AsyncSession = Depends(get_db_session)):
    """User repository factory."""
    from app.modules.users.repository import UserRepository
    return UserRepository(db)


def get_library_repository(db: AsyncSession = Depends(get_db_session)):
    """Library repository factory."""
    from app.modules.libraries.repository import LibraryRepository
    return LibraryRepository(db)


def get_people_cluster_label_repository(db: AsyncSession = Depends(get_db_session)):
    """People cluster label repository factory."""
    from app.modules.people.repository import PeopleClusterLabelRepository
    return PeopleClusterLabelRepository(db)


async def get_search_service(
    db: AsyncSession = Depends(get_db_session),
    opensearch=Depends(get_opensearch_client),
):
    """Search service factory with injected dependencies."""
    from app.modules.search.service import SearchService
    return SearchService(db, opensearch)


def get_auth_service(db: AsyncSession = Depends(get_db_session)):
    """Auth service factory."""
    from app.modules.auth.service import AuthService
    return AuthService(db)
