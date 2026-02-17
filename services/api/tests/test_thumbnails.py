from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.modules.ingest.auth import verify_agent_token
from app.modules.tenancy import OrgContext, get_current_org


def _startup_patches():
    segment_client = MagicMock()
    segment_client.close = AsyncMock()

    scene_client = MagicMock()
    scene_client.close = AsyncMock()

    startup_engine = MagicMock()
    startup_engine.dispose = AsyncMock()

    return [
        patch("app.modules.search.client.OpenSearchClient", return_value=segment_client),
        patch("app.modules.search.scene_client.SceneSearchClient", return_value=scene_client),
        patch("app.db.base.get_async_engine", return_value=startup_engine),
        patch("app.main._startup_search_checks", new=AsyncMock()),
        patch("app.main._startup_scene_search_checks", new=AsyncMock()),
    ]


def _make_org_context() -> OrgContext:
    return OrgContext(org_id=uuid4(), org_slug="devorg")


def test_upload_and_retrieve_thumbnail(tmp_path: Path):
    org_ctx = _make_org_context()
    settings = Settings(thumbnail_storage_dir=str(tmp_path))

    async def _mock_verify_agent_token() -> OrgContext:
        return org_ctx

    async def _mock_get_current_org() -> OrgContext:
        return org_ctx

    app.dependency_overrides[verify_agent_token] = _mock_verify_agent_token
    app.dependency_overrides[get_current_org] = _mock_get_current_org

    startup_patchers = _startup_patches()
    try:
        with startup_patchers[0], startup_patchers[1], startup_patchers[2], startup_patchers[3], startup_patchers[4]:
            with patch("app.modules.thumbnails.router.get_settings", return_value=settings):
                with TestClient(app) as client:
                    upload = client.post(
                        "/api/ingest/thumbnails/video-1",
                        headers={"host": "devorg.app.heimdex.local", "authorization": "Bearer test"},
                        data={"scene_id": "video-1_scene_0"},
                        files={"file": ("thumb.jpg", b"\xff\xd8\xff\xd9", "image/jpeg")},
                    )

                    assert upload.status_code == 200
                    assert upload.json() == {"stored": True, "path": "video-1/video-1_scene_0"}

                    response = client.get(
                        "/api/thumbnails/video-1/video-1_scene_0",
                        headers={"host": "devorg.app.heimdex.local"},
                    )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/jpeg")
        assert response.headers["cache-control"] == "public, max-age=86400"
        assert response.content == b"\xff\xd8\xff\xd9"
    finally:
        app.dependency_overrides.clear()


def test_get_thumbnail_404_when_missing(tmp_path: Path):
    settings = Settings(thumbnail_storage_dir=str(tmp_path))
    org_ctx = _make_org_context()

    async def _mock_get_current_org() -> OrgContext:
        return org_ctx

    app.dependency_overrides[get_current_org] = _mock_get_current_org

    startup_patchers = _startup_patches()
    try:
        with startup_patchers[0], startup_patchers[1], startup_patchers[2], startup_patchers[3], startup_patchers[4]:
            with patch("app.modules.thumbnails.router.get_settings", return_value=settings):
                with TestClient(app) as client:
                    response = client.get(
                        "/api/thumbnails/video-1/video-1_scene_404",
                        headers={"host": "devorg.app.heimdex.local"},
                    )

        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_upload_requires_auth(tmp_path: Path):
    settings = Settings(thumbnail_storage_dir=str(tmp_path))

    startup_patchers = _startup_patches()
    with startup_patchers[0], startup_patchers[1], startup_patchers[2], startup_patchers[3], startup_patchers[4]:
        with patch("app.modules.thumbnails.router.get_settings", return_value=settings):
            with TestClient(app) as client:
                response = client.post(
                    "/api/ingest/thumbnails/video-1",
                    headers={"host": "devorg.app.heimdex.local"},
                    data={"scene_id": "video-1_scene_0"},
                    files={"file": ("thumb.jpg", b"\xff\xd8\xff\xd9", "image/jpeg")},
                )

    assert response.status_code == 401


def test_get_thumbnail_is_public_no_auth_header(tmp_path: Path):
    org_ctx = _make_org_context()
    storage_dir = tmp_path / str(org_ctx.org_id) / "video-1"
    storage_dir.mkdir(parents=True)
    thumbnail_path = storage_dir / "video-1_scene_0.jpg"
    thumbnail_path.write_bytes(b"\xff\xd8\xff\xd9")
    settings = Settings(thumbnail_storage_dir=str(tmp_path))

    async def _mock_get_current_org() -> OrgContext:
        return org_ctx

    app.dependency_overrides[get_current_org] = _mock_get_current_org

    startup_patchers = _startup_patches()
    try:
        with startup_patchers[0], startup_patchers[1], startup_patchers[2], startup_patchers[3], startup_patchers[4]:
            with patch("app.modules.thumbnails.router.get_settings", return_value=settings):
                with TestClient(app) as client:
                    response = client.get(
                        "/api/thumbnails/video-1/video-1_scene_0",
                        headers={"host": "devorg.app.heimdex.local"},
                    )

        assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_upload_and_retrieve_face_thumbnail(tmp_path: Path):
    org_ctx = _make_org_context()
    settings = Settings(thumbnail_storage_dir=str(tmp_path))

    async def _mock_verify_agent_token() -> OrgContext:
        return org_ctx

    async def _mock_get_current_org() -> OrgContext:
        return org_ctx

    app.dependency_overrides[verify_agent_token] = _mock_verify_agent_token
    app.dependency_overrides[get_current_org] = _mock_get_current_org

    startup_patchers = _startup_patches()
    try:
        with startup_patchers[0], startup_patchers[1], startup_patchers[2], startup_patchers[3], startup_patchers[4]:
            with patch("app.modules.thumbnails.router.get_settings", return_value=settings):
                with TestClient(app) as client:
                    upload = client.post(
                        "/api/ingest/thumbnails/face/person-cluster-1",
                        headers={"host": "devorg.app.heimdex.local", "authorization": "Bearer test"},
                        files={"file": ("face.jpg", b"\xff\xd8\xff\xd9", "image/jpeg")},
                    )

                    assert upload.status_code == 200
                    assert upload.json() == {"stored": True, "path": "faces/person-cluster-1"}

                    response = client.get(
                        "/api/thumbnails/faces/person-cluster-1",
                        headers={"host": "devorg.app.heimdex.local"},
                    )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/jpeg")
        assert response.headers["cache-control"] == "public, max-age=86400"
        assert response.content == b"\xff\xd8\xff\xd9"
    finally:
        app.dependency_overrides.clear()


def test_upload_face_thumbnail_wrong_content_type(tmp_path: Path):
    org_ctx = _make_org_context()
    settings = Settings(thumbnail_storage_dir=str(tmp_path))

    async def _mock_verify_agent_token() -> OrgContext:
        return org_ctx

    app.dependency_overrides[verify_agent_token] = _mock_verify_agent_token

    startup_patchers = _startup_patches()
    try:
        with startup_patchers[0], startup_patchers[1], startup_patchers[2], startup_patchers[3], startup_patchers[4]:
            with patch("app.modules.thumbnails.router.get_settings", return_value=settings):
                with TestClient(app) as client:
                    response = client.post(
                        "/api/ingest/thumbnails/face/person-cluster-1",
                        headers={"host": "devorg.app.heimdex.local", "authorization": "Bearer test"},
                        files={"file": ("face.png", b"\x89PNG\r\n\x1a\n", "image/png")},
                    )

                    assert response.status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_get_face_thumbnail_404_when_missing(tmp_path: Path):
    settings = Settings(thumbnail_storage_dir=str(tmp_path))
    org_ctx = _make_org_context()

    async def _mock_get_current_org() -> OrgContext:
        return org_ctx

    app.dependency_overrides[get_current_org] = _mock_get_current_org

    startup_patchers = _startup_patches()
    try:
        with startup_patchers[0], startup_patchers[1], startup_patchers[2], startup_patchers[3], startup_patchers[4]:
            with patch("app.modules.thumbnails.router.get_settings", return_value=settings):
                with TestClient(app) as client:
                    response = client.get(
                        "/api/thumbnails/faces/person-cluster-404",
                        headers={"host": "devorg.app.heimdex.local"},
                    )

        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
