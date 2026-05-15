import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

# Force-load the full SQLAlchemy model registry before any test configures
# a mapper. Without this, tests that import a single model directly (e.g.
# `from app.modules.search.models import SearchEvent`) trigger Library's
# `LibraryProfile` relationship forward-ref while the profiles module
# hasn't been imported yet, producing:
#   InvalidRequestError: expression 'LibraryProfile' failed to locate a name
import app.db.models  # noqa: F401

from app.modules.tenancy.context import OrgContext


TESTS_ROOT = Path(__file__).resolve().parent
API_ROOT = TESTS_ROOT.parent
CORE_TEST_FILE_MANIFEST = TESTS_ROOT / "core_test_files.txt"


def _load_core_test_files() -> set[str]:
    if not CORE_TEST_FILE_MANIFEST.exists():
        return set()
    return {
        line.strip()
        for line in CORE_TEST_FILE_MANIFEST.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


CORE_TEST_FILES = _load_core_test_files()


def pytest_collection_modifyitems(items):
    """Apply lane markers from central manifests during the migration.

    This keeps the current path-based CI allowlist and the new marker-based
    `core` lane in sync without touching dozens of stable test files at once.
    """
    core_marker = pytest.mark.core
    for item in items:
        relpath = Path(item.fspath).resolve().relative_to(API_ROOT).as_posix()
        if relpath in CORE_TEST_FILES:
            item.add_marker(core_marker)


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
    client.search_visual_vector = AsyncMock(return_value=[])
    client.search_metadata = AsyncMock(return_value=[])
    client.get_facets = AsyncMock(return_value={"libraries": [], "source_types": [], "people": []})
    client.close = AsyncMock()
    return client
