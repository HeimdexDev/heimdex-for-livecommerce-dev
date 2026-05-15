"""
Unit tests for the "similar faces" feature.

Tests verify:
1. Endpoint returns ranked results in descending similarity order
2. Correct cluster_id (self) is forwarded to the repository (SQL handles exclusion)
3. Custom threshold is passed through to the repository
4. Custom limit is passed through to the repository
5. Empty repository result produces an empty response with total=0
6. threshold query param validation: values outside [0, 1] return 422
7. limit query param validation: values outside [1, 50] return 422
8. When people_enabled=false, endpoint returns 404

Run with: pytest tests/test_people_similar.py -v
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.modules.tenancy import OrgContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_org_ctx():
    return OrgContext(org_id=uuid4(), org_slug="testorg")


def _make_user():
    user = MagicMock()
    user.id = uuid4()
    return user


def _make_face_repo(similar_rows=None):
    repo = AsyncMock()
    repo.find_similar_identities = AsyncMock(return_value=similar_rows or [])
    return repo


# ---------------------------------------------------------------------------
# Endpoint functional tests (direct router function calls)
# ---------------------------------------------------------------------------
class TestSimilarPeopleEndpoint:

    @pytest.mark.asyncio
    async def test_similar_endpoint_returns_ranked_results(self):
        """Mock returns 3 rows; response schema is correct and order is descending."""
        from app.modules.people.router import find_similar_people
        from app.modules.face.repository import SimilarIdentityRow

        rows = [
            SimilarIdentityRow(cluster_id="c_a", similarity=0.92, thumbnail_source="auto"),
            SimilarIdentityRow(cluster_id="c_b", similarity=0.75, thumbnail_source="auto"),
            SimilarIdentityRow(cluster_id="c_c", similarity=0.61, thumbnail_source="auto"),
        ]
        face_repo = _make_face_repo(rows)

        with patch("app.modules.people.router.get_settings") as mock_settings:
            mock_settings.return_value.people_enabled = True

            response = await find_similar_people(
                person_cluster_id="target_cluster",
                threshold=0.40,
                limit=20,
                org_ctx=_make_org_ctx(),
                user=_make_user(),
                face_repo=face_repo,
            )

        assert response.target_cluster_id == "target_cluster"
        assert response.total == 3
        assert response.threshold == 0.40
        assert len(response.similarities) == 3

        # Results must preserve the order returned by the repository (descending)
        similarities = [item.similarity for item in response.similarities]
        assert similarities == sorted(similarities, reverse=True)
        assert response.similarities[0].person_cluster_id == "c_a"
        assert response.similarities[1].person_cluster_id == "c_b"
        assert response.similarities[2].person_cluster_id == "c_c"

    @pytest.mark.asyncio
    async def test_similar_excludes_self(self):
        """Endpoint forwards the correct cluster_id so SQL can exclude self."""
        from app.modules.people.router import find_similar_people

        face_repo = _make_face_repo([])

        with patch("app.modules.people.router.get_settings") as mock_settings:
            mock_settings.return_value.people_enabled = True

            await find_similar_people(
                person_cluster_id="self_cluster_id",
                threshold=0.40,
                limit=20,
                org_ctx=_make_org_ctx(),
                user=_make_user(),
                face_repo=face_repo,
            )

        face_repo.find_similar_identities.assert_called_once()
        call_kwargs = face_repo.find_similar_identities.call_args.kwargs
        assert call_kwargs["cluster_id"] == "self_cluster_id"

    @pytest.mark.asyncio
    async def test_similar_respects_threshold(self):
        """Custom threshold value is forwarded to the repository unchanged."""
        from app.modules.people.router import find_similar_people

        face_repo = _make_face_repo([])

        with patch("app.modules.people.router.get_settings") as mock_settings:
            mock_settings.return_value.people_enabled = True

            response = await find_similar_people(
                person_cluster_id="some_cluster",
                threshold=0.75,
                limit=20,
                org_ctx=_make_org_ctx(),
                user=_make_user(),
                face_repo=face_repo,
            )

        call_kwargs = face_repo.find_similar_identities.call_args.kwargs
        assert call_kwargs["threshold"] == 0.75
        assert response.threshold == 0.75

    @pytest.mark.asyncio
    async def test_similar_respects_limit(self):
        """Custom limit value is forwarded to the repository unchanged."""
        from app.modules.people.router import find_similar_people

        face_repo = _make_face_repo([])

        with patch("app.modules.people.router.get_settings") as mock_settings:
            mock_settings.return_value.people_enabled = True

            await find_similar_people(
                person_cluster_id="some_cluster",
                threshold=0.40,
                limit=5,
                org_ctx=_make_org_ctx(),
                user=_make_user(),
                face_repo=face_repo,
            )

        call_kwargs = face_repo.find_similar_identities.call_args.kwargs
        assert call_kwargs["limit"] == 5

    @pytest.mark.asyncio
    async def test_similar_empty_when_no_matches(self):
        """Repository returns empty list; response has total=0 and empty similarities."""
        from app.modules.people.router import find_similar_people

        face_repo = _make_face_repo([])

        with patch("app.modules.people.router.get_settings") as mock_settings:
            mock_settings.return_value.people_enabled = True

            response = await find_similar_people(
                person_cluster_id="lonely_cluster",
                threshold=0.40,
                limit=20,
                org_ctx=_make_org_ctx(),
                user=_make_user(),
                face_repo=face_repo,
            )

        assert response.total == 0
        assert response.similarities == []
        assert response.target_cluster_id == "lonely_cluster"

    @pytest.mark.asyncio
    async def test_similar_people_disabled(self):
        """When people_enabled=false, endpoint raises 404 HTTPException."""
        from fastapi import HTTPException
        from app.modules.people.router import find_similar_people

        face_repo = _make_face_repo([])

        with patch("app.modules.people.router.get_settings") as mock_settings:
            mock_settings.return_value.people_enabled = False

            with pytest.raises(HTTPException) as exc_info:
                await find_similar_people(
                    person_cluster_id="some_cluster",
                    threshold=0.40,
                    limit=20,
                    org_ctx=_make_org_ctx(),
                    user=_make_user(),
                    face_repo=face_repo,
                )

        assert exc_info.value.status_code == 404
        face_repo.find_similar_identities.assert_not_called()


# ---------------------------------------------------------------------------
# Query param validation tests (HTTP-level, need TestClient)
# ---------------------------------------------------------------------------
class TestSimilarPeopleValidation:
    """Test FastAPI query param validation for threshold and limit."""

    @pytest.fixture(autouse=True)
    def _client(self):
        from unittest.mock import AsyncMock, MagicMock, patch
        from fastapi.testclient import TestClient
        from app.main import app
        from app.modules.auth import get_current_user
        from app.modules.tenancy import get_current_org
        from app.dependencies import get_face_repository

        org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
        user = MagicMock()
        user.id = uuid4()

        app.dependency_overrides[get_current_org] = lambda: org_ctx
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_face_repository] = lambda: _make_face_repo([])

        startup_patches = [
            patch("app.modules.search.client.OpenSearchClient", return_value=MagicMock(close=AsyncMock())),
            patch("app.modules.search.scene_client.SceneSearchClient", return_value=MagicMock(close=AsyncMock())),
            patch("app.db.base.get_async_engine", return_value=MagicMock(dispose=AsyncMock())),
            patch("app.main._startup_search_checks", new=AsyncMock()),
            patch("app.main._startup_scene_search_checks", new=AsyncMock()),
            patch("app.main._verify_org_auth0_bindings", new=AsyncMock()),
            patch("app.main._ensure_search_event_partitions", new=AsyncMock()),
            patch("app.modules.people.router.get_settings", return_value=MagicMock(people_enabled=True)),
        ]
        for p in startup_patches:
            p.start()

        self.client = TestClient(app, raise_server_exceptions=False)

        yield

        app.dependency_overrides.clear()
        for p in startup_patches:
            p.stop()

    def test_similar_threshold_too_high_returns_422(self):
        resp = self.client.get("/api/people/cluster_1/similar?threshold=1.5")
        assert resp.status_code == 422

    def test_similar_threshold_negative_returns_422(self):
        resp = self.client.get("/api/people/cluster_1/similar?threshold=-0.1")
        assert resp.status_code == 422

    def test_similar_limit_too_high_returns_422(self):
        resp = self.client.get("/api/people/cluster_1/similar?limit=51")
        assert resp.status_code == 422

    def test_similar_limit_zero_returns_422(self):
        resp = self.client.get("/api/people/cluster_1/similar?limit=0")
        assert resp.status_code == 422
