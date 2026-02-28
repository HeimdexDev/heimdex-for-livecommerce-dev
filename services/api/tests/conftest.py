import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.modules.tenancy.context import OrgContext


@pytest.fixture
def org_context():
    return OrgContext(org_id=uuid4(), org_slug="testorg")


@pytest.fixture
def mock_db_session():
    session = AsyncMock()
    return session


@pytest.fixture
def mock_opensearch_client():
    client = MagicMock()
    client.search_lexical = AsyncMock(return_value=[])
    client.search_vector = AsyncMock(return_value=[])
    client.get_facets = AsyncMock(return_value={"libraries": [], "source_types": [], "people": []})
    client.close = AsyncMock()
    return client


@pytest.fixture
def mock_scene_opensearch_client():
    """Mock SceneSearchClient for unit tests."""
    client = MagicMock()
    client.search_lexical = AsyncMock(return_value=[])
    client.search_vector = AsyncMock(return_value=[])
    client.search_metadata = AsyncMock(return_value=[])
    client.get_facets = AsyncMock(return_value={"libraries": [], "source_types": [], "people": []})
    client.close = AsyncMock()
    return client