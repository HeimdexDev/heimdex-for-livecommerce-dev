"""
Centralized dependency injection providers for Heimdex API.

All FastAPI route dependencies should be imported from this module.

DI Pattern:
- Long-lived resources (OpenSearch client) are created at app startup via lifespan
- Resources are stored in app.state for access via Request
- Services are created per-request via dependency factories
"""
from typing import AsyncGenerator

import hmac

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db_session as _get_db_session


get_db_session = _get_db_session


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


def get_people_exclude_preference_repository(db: AsyncSession = Depends(get_db_session)):
    """People exclude preference repository factory."""
    from app.modules.people.repository import PeopleExcludePreferenceRepository
    return PeopleExcludePreferenceRepository(db)


def get_people_video_exclusion_repository(db: AsyncSession = Depends(get_db_session)):
    """People video exclusion repository factory."""
    from app.modules.people.repository import PeopleVideoExclusionRepository
    return PeopleVideoExclusionRepository(db)


def get_face_repository(db: AsyncSession = Depends(get_db_session)):
    """Face repository factory."""
    from app.modules.face.repository import FaceRepository
    return FaceRepository(db)


def get_basket_repository(db: AsyncSession = Depends(get_db_session)):
    """Scene basket repository factory."""
    from app.modules.basket.repository import SceneBasketRepository
    return SceneBasketRepository(db)


def get_youtube_channel_repository(db: AsyncSession = Depends(get_db_session)):
    from app.modules.youtube.repository import YouTubeChannelRepository
    return YouTubeChannelRepository(db)


def get_youtube_video_repository(db: AsyncSession = Depends(get_db_session)):
    from app.modules.youtube.repository import YouTubeVideoRepository
    return YouTubeVideoRepository(db)


def get_drive_connection_repository(db: AsyncSession = Depends(get_db_session)):
    """Drive connection repository factory."""
    from app.modules.drive.repository import DriveConnectionRepository
    return DriveConnectionRepository(db)


def get_drive_file_repository(db: AsyncSession = Depends(get_db_session)):
    """Drive file repository factory."""
    from app.modules.drive.repository import DriveFileRepository
    return DriveFileRepository(db)


def get_drive_secret_repository(db: AsyncSession = Depends(get_db_session)):
    """Drive secret repository factory."""
    from app.modules.drive.repository import DriveSecretRepository
    return DriveSecretRepository(db)


def get_watched_folder_repository(db: AsyncSession = Depends(get_db_session)):
    """Watched folder repository factory."""
    from app.modules.drive.watched_folder_repository import WatchedFolderRepository
    return WatchedFolderRepository(db)


def get_export_record_repository(db: AsyncSession = Depends(get_db_session)):
    """Export record repository factory."""
    from app.modules.export.repository import ExportRecordRepository
    return ExportRecordRepository(db)


def get_reprocess_repository(db: AsyncSession = Depends(get_db_session)):
    """Reprocess repository factory."""
    from app.modules.videos.reprocess_repository import ReprocessRepository
    return ReprocessRepository(db)


def get_org_repository(db: AsyncSession = Depends(get_db_session)):
    """Organization repository factory."""
    from app.modules.orgs.repository import OrgRepository
    return OrgRepository(db)


def get_agent_intent_repository(db: AsyncSession = Depends(get_db_session)):
    """Agent intent repository factory."""
    from app.modules.agent_intents.repository import AgentIntentRepository
    return AgentIntentRepository(db)


def get_saved_short_repository(db: AsyncSession = Depends(get_db_session)):
    """Saved short repository factory."""
    from app.modules.shorts.repository import SavedShortRepository
    return SavedShortRepository(db)


def get_shorts_render_repository(db: AsyncSession = Depends(get_db_session)):
    """Shorts render job repository factory."""
    from app.modules.shorts_render.repository import ShortsRenderJobRepository
    return ShortsRenderJobRepository(db)


def get_shorts_render_service(
    repo=Depends(get_shorts_render_repository),
    scene_search=Depends(get_scene_opensearch_client),
):
    """Shorts render service factory."""
    from app.modules.shorts_render.service import ShortsRenderService
    return ShortsRenderService(repo, scene_search)


def get_text_template_repository(db: AsyncSession = Depends(get_db_session)):
    """Text template repository factory."""
    from app.modules.text_templates.repository import TextTemplateRepository
    return TextTemplateRepository(db)


def get_pairing_code_repository(db: AsyncSession = Depends(get_db_session)):
    """Pairing code repository factory."""
    from app.modules.devices.pairing import PairingCodeRepository
    return PairingCodeRepository(db)


def get_library_profile_repository(db: AsyncSession = Depends(get_db_session)):
    """Library profile repository factory."""
    from app.modules.profiles.repository import LibraryProfileRepository
    return LibraryProfileRepository(db)


async def get_search_service(
    db: AsyncSession = Depends(get_db_session),
    opensearch=Depends(get_opensearch_client),
):
    """Search service factory with injected dependencies."""
    from app.modules.search.service import SearchService
    return SearchService(db, opensearch)


async def get_scene_search_service(
    db: AsyncSession = Depends(get_db_session),
    scene_opensearch=Depends(get_scene_opensearch_client),
):
    """Scene search service factory with injected dependencies."""
    from app.modules.search.scene_service import SceneSearchService
    return SceneSearchService(db, scene_opensearch)


async def get_scene_ingest_service(
    db: AsyncSession = Depends(get_db_session),
    scene_opensearch=Depends(get_scene_opensearch_client),
):
    """Scene ingest service factory with injected dependencies."""
    from app.modules.ingest.service import SceneIngestService
    return SceneIngestService(db, scene_opensearch)


async def get_video_service(
    db: AsyncSession = Depends(get_db_session),
    scene_opensearch=Depends(get_scene_opensearch_client),
):
    """Video service factory with injected dependencies."""
    from app.modules.videos.service import VideoService
    return VideoService(db, scene_opensearch)


def get_grouping_service(
    scene_opensearch=Depends(get_scene_opensearch_client),
):
    from app.modules.grouping.service import GroupingService
    return GroupingService(scene_opensearch)


def get_device_repository(db: AsyncSession = Depends(get_db_session)):
    """Device repository factory."""
    from app.modules.devices.repository import DeviceRepository
    return DeviceRepository(db)


def get_search_event_repository(db: AsyncSession = Depends(get_db_session)):
    """Search event analytics repository factory."""
    from app.modules.search.search_event_repository import SearchEventRepository
    return SearchEventRepository(db)


def get_auth_service(db: AsyncSession = Depends(get_db_session)):
    """Auth service factory."""
    auth_module = __import__("app.modules.auth.service", fromlist=["AuthService"])
    return auth_module.AuthService(db)


async def verify_internal_token(
    authorization: str = Header(..., alias="Authorization"),
) -> str:
    from app.logging_config import get_logger

    _logger = get_logger("internal_auth")
    settings = get_settings()

    if not settings.drive_internal_api_key:
        _logger.error("drive_internal_api_key_not_configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Internal API not configured",
        )

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header",
        )

    token = parts[1]
    if not hmac.compare_digest(token, settings.drive_internal_api_key):
        _logger.warning("internal_auth_invalid_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal API key",
        )

    return token
