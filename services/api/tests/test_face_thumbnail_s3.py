"""Tests for face thumbnail S3 migration: key helpers, S3 fallback reads, dual-write."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.modules.ingest.auth import verify_agent_token
from app.modules.tenancy import OrgContext, get_current_org


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

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
        patch("app.main._verify_org_auth0_bindings", new=AsyncMock()),
        patch("app.main._ensure_search_event_partitions", new=AsyncMock()),
    ]


def _make_org_context() -> OrgContext:
    return OrgContext(org_id=uuid4(), org_slug="devorg")


def _setup_client(tmp_path):
    org_ctx = _make_org_context()
    settings = Settings(thumbnail_storage_dir=str(tmp_path))

    async def _mock_verify_agent_token() -> OrgContext:
        return org_ctx

    async def _mock_get_current_org() -> OrgContext:
        return org_ctx

    app.dependency_overrides[verify_agent_token] = _mock_verify_agent_token
    app.dependency_overrides[get_current_org] = _mock_get_current_org
    return org_ctx, settings


# ---------------------------------------------------------------------------
# S3 key helper tests
# ---------------------------------------------------------------------------

class TestS3KeyHelpers:
    def test_face_thumbnail_s3_key(self):
        from app.modules.drive.keys import face_thumbnail_s3_key
        assert face_thumbnail_s3_key("org-123", "person_abc") == "org-123/faces/person_abc.jpg"

    def test_exemplar_thumbnail_s3_key(self):
        from app.modules.drive.keys import exemplar_thumbnail_s3_key
        assert exemplar_thumbnail_s3_key("org-123", "ex-456") == "org-123/faces/exemplars/ex-456.jpg"

    def test_face_thumbnail_s3_prefix(self):
        from app.modules.drive.keys import face_thumbnail_s3_prefix
        assert face_thumbnail_s3_prefix("org-123") == "org-123/faces/"

    def test_keys_dont_collide_with_scene_thumbnails(self):
        from app.modules.drive.keys import face_thumbnail_s3_key, thumbnail_s3_key
        face_key = face_thumbnail_s3_key("org-1", "person_1")
        scene_key = thumbnail_s3_key("org-1", "video-1", "scene-1")
        assert face_key != scene_key
        assert "/faces/" in face_key
        assert "/drive/thumbs/" in scene_key


# ---------------------------------------------------------------------------
# S3 fallback read tests
# ---------------------------------------------------------------------------

class TestFaceThumbnailS3Fallback:
    def test_face_thumbnail_disk_hit_no_s3_call(self, tmp_path: Path):
        """When disk file exists, S3 should not be called."""
        org_ctx, settings = _setup_client(tmp_path)

        face_dir = tmp_path / str(org_ctx.org_id) / "faces"
        face_dir.mkdir(parents=True)
        (face_dir / "person-1.jpg").write_bytes(b"\xff\xd8\xff\xd9")

        startup_patchers = _startup_patches()
        try:
            with startup_patchers[0], startup_patchers[1], startup_patchers[2], startup_patchers[3], startup_patchers[4], startup_patchers[5], startup_patchers[6]:
                with patch("app.modules.thumbnails.router.get_settings", return_value=settings):
                    with patch("app.modules.thumbnails.router._get_s3_face_thumbnail") as mock_s3:
                        with TestClient(app) as client:
                            resp = client.get(
                                "/api/thumbnails/faces/person-1",
                                headers={"host": "devorg.app.heimdex.local"},
                            )

            assert resp.status_code == 200
            assert resp.content == b"\xff\xd8\xff\xd9"
            mock_s3.assert_not_called()
        finally:
            app.dependency_overrides.clear()

    def test_face_thumbnail_s3_fallback_when_disk_missing(self, tmp_path: Path):
        """When disk file is missing, should fall back to S3."""
        org_ctx, settings = _setup_client(tmp_path)

        mock_s3_client = MagicMock()
        mock_s3_client.get_object_bytes_async = AsyncMock(return_value=b"\xff\xd8\xff\xe0")

        startup_patchers = _startup_patches()
        try:
            with startup_patchers[0], startup_patchers[1], startup_patchers[2], startup_patchers[3], startup_patchers[4], startup_patchers[5], startup_patchers[6]:
                with patch("app.modules.thumbnails.router.get_settings", return_value=settings):
                    with patch("app.storage.s3.S3Client", return_value=mock_s3_client):
                        with TestClient(app) as client:
                            resp = client.get(
                                "/api/thumbnails/faces/person-1",
                                headers={"host": "devorg.app.heimdex.local"},
                            )

            assert resp.status_code == 200
            assert resp.content == b"\xff\xd8\xff\xe0"
            assert resp.headers["cache-control"] == "public, max-age=60"
        finally:
            app.dependency_overrides.clear()

    def test_face_thumbnail_404_when_both_disk_and_s3_missing(self, tmp_path: Path):
        """When both disk and S3 are missing, should return 404."""
        org_ctx, settings = _setup_client(tmp_path)

        mock_s3_client = MagicMock()
        mock_s3_client.get_object_bytes_async = AsyncMock(return_value=None)

        startup_patchers = _startup_patches()
        try:
            with startup_patchers[0], startup_patchers[1], startup_patchers[2], startup_patchers[3], startup_patchers[4], startup_patchers[5], startup_patchers[6]:
                with patch("app.modules.thumbnails.router.get_settings", return_value=settings):
                    with patch("app.storage.s3.S3Client", return_value=mock_s3_client):
                        with TestClient(app) as client:
                            resp = client.get(
                                "/api/thumbnails/faces/person-1",
                                headers={"host": "devorg.app.heimdex.local"},
                            )

            assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_exemplar_thumbnail_s3_fallback(self, tmp_path: Path):
        """When exemplar disk file is missing, should fall back to S3."""
        org_ctx, settings = _setup_client(tmp_path)

        mock_s3_client = MagicMock()
        mock_s3_client.get_object_bytes_async = AsyncMock(return_value=b"\xff\xd8\xff\xe1")

        startup_patchers = _startup_patches()
        try:
            with startup_patchers[0], startup_patchers[1], startup_patchers[2], startup_patchers[3], startup_patchers[4], startup_patchers[5], startup_patchers[6]:
                with patch("app.modules.thumbnails.router.get_settings", return_value=settings):
                    with patch("app.storage.s3.S3Client", return_value=mock_s3_client):
                        with TestClient(app) as client:
                            resp = client.get(
                                "/api/thumbnails/faces/exemplars/ex-uuid-1",
                                headers={"host": "devorg.app.heimdex.local"},
                            )

            assert resp.status_code == 200
            assert resp.content == b"\xff\xd8\xff\xe1"
            assert resp.headers["cache-control"] == "public, max-age=604800"
        finally:
            app.dependency_overrides.clear()

    def test_exemplar_thumbnail_disk_preferred_over_s3(self, tmp_path: Path):
        """Disk file should be preferred over S3."""
        org_ctx, settings = _setup_client(tmp_path)

        exemplar_dir = tmp_path / str(org_ctx.org_id) / "faces" / "exemplars"
        exemplar_dir.mkdir(parents=True)
        (exemplar_dir / "ex-1.jpg").write_bytes(b"\xff\xd8disk")

        startup_patchers = _startup_patches()
        try:
            with startup_patchers[0], startup_patchers[1], startup_patchers[2], startup_patchers[3], startup_patchers[4], startup_patchers[5], startup_patchers[6]:
                with patch("app.modules.thumbnails.router.get_settings", return_value=settings):
                    with patch("app.modules.thumbnails.router._get_s3_face_thumbnail") as mock_s3:
                        with TestClient(app) as client:
                            resp = client.get(
                                "/api/thumbnails/faces/exemplars/ex-1",
                                headers={"host": "devorg.app.heimdex.local"},
                            )

            assert resp.status_code == 200
            assert resp.content == b"\xff\xd8disk"
            mock_s3.assert_not_called()
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Dual-write tests: S3 failure should not break uploads
# ---------------------------------------------------------------------------

class TestDualWriteResilience:
    def test_face_upload_succeeds_when_s3_fails(self, tmp_path: Path):
        """Face thumbnail upload should succeed even if S3 upload fails."""
        org_ctx, settings = _setup_client(tmp_path)

        mock_s3_client = MagicMock()
        mock_s3_client.upload_file_async = AsyncMock(side_effect=Exception("S3 down"))

        startup_patchers = _startup_patches()
        try:
            with startup_patchers[0], startup_patchers[1], startup_patchers[2], startup_patchers[3], startup_patchers[4], startup_patchers[5], startup_patchers[6]:
                with patch("app.modules.thumbnails.router.get_settings", return_value=settings):
                    with patch("app.storage.s3.S3Client", return_value=mock_s3_client):
                        with TestClient(app) as client:
                            resp = client.post(
                                "/api/ingest/thumbnails/face/person-1",
                                headers={
                                    "host": "devorg.app.heimdex.local",
                                    "authorization": "Bearer test",
                                },
                                files={"file": ("face.jpg", b"\xff\xd8\xff\xd9", "image/jpeg")},
                            )

            assert resp.status_code == 200
            assert resp.json()["stored"] is True

            # Verify disk write still happened
            face_path = tmp_path / str(org_ctx.org_id) / "faces" / "person-1.jpg"
            assert face_path.exists()
            assert face_path.read_bytes() == b"\xff\xd8\xff\xd9"
        finally:
            app.dependency_overrides.clear()

    def test_face_upload_writes_to_both_disk_and_s3(self, tmp_path: Path):
        """When S3 is available, face thumbnail should be written to both."""
        org_ctx, settings = _setup_client(tmp_path)

        mock_s3_client = MagicMock()
        mock_s3_client.upload_file_async = AsyncMock()

        startup_patchers = _startup_patches()
        try:
            with startup_patchers[0], startup_patchers[1], startup_patchers[2], startup_patchers[3], startup_patchers[4], startup_patchers[5], startup_patchers[6]:
                with patch("app.modules.thumbnails.router.get_settings", return_value=settings):
                    with patch("app.storage.s3.S3Client", return_value=mock_s3_client):
                        with TestClient(app) as client:
                            resp = client.post(
                                "/api/ingest/thumbnails/face/person-1",
                                headers={
                                    "host": "devorg.app.heimdex.local",
                                    "authorization": "Bearer test",
                                },
                                files={"file": ("face.jpg", b"\xff\xd8\xff\xd9", "image/jpeg")},
                            )

            assert resp.status_code == 200
            # Disk write
            face_path = tmp_path / str(org_ctx.org_id) / "faces" / "person-1.jpg"
            assert face_path.exists()
            # S3 write
            mock_s3_client.upload_file_async.assert_called_once()
            call_args = mock_s3_client.upload_file_async.call_args
            assert "faces/person-1.jpg" in str(call_args)
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Backfill script tests
# ---------------------------------------------------------------------------

class TestBackfillScript:
    def _run_backfill(self, argv, tmp_path, mock_s3):
        """Helper to run backfill with proper patching."""
        import sys
        from importlib import reload

        with patch.object(sys, "argv", argv):
            with patch("app.cli.backfill_face_thumbnails_to_s3.get_settings") as mock_settings:
                mock_settings.return_value = MagicMock(
                    thumbnail_storage_dir=str(tmp_path),
                    drive_s3_bucket="test-bucket",
                )
                with patch("app.cli.backfill_face_thumbnails_to_s3.S3Client", return_value=mock_s3):
                    import app.cli.backfill_face_thumbnails_to_s3 as mod
                    reload(mod)
                    # Re-patch after reload
                    with patch.object(mod, "get_settings", mock_settings):
                        with patch.object(mod, "S3Client", return_value=mock_s3):
                            mod.main()

    def test_backfill_dry_run(self, tmp_path: Path):
        """Dry run should not upload anything."""
        org_id = str(uuid4())
        face_dir = tmp_path / org_id / "faces"
        face_dir.mkdir(parents=True)
        (face_dir / "person-1.jpg").write_bytes(b"\xff\xd8\xff\xd9")

        exemplar_dir = face_dir / "exemplars"
        exemplar_dir.mkdir()
        (exemplar_dir / "ex-1.jpg").write_bytes(b"\xff\xd8\xff\xe0")

        mock_s3 = MagicMock()
        self._run_backfill(["prog", "--dry-run"], tmp_path, mock_s3)
        mock_s3.upload_file.assert_not_called()

    def test_backfill_uploads_faces_and_exemplars(self, tmp_path: Path):
        """Backfill should upload both face and exemplar thumbnails."""
        org_id = str(uuid4())
        face_dir = tmp_path / org_id / "faces"
        face_dir.mkdir(parents=True)
        (face_dir / "person-1.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        (face_dir / "person-2.jpg").write_bytes(b"\xff\xd8\xff\xd9")

        exemplar_dir = face_dir / "exemplars"
        exemplar_dir.mkdir()
        (exemplar_dir / "ex-1.jpg").write_bytes(b"\xff\xd8\xff\xe0")

        mock_s3 = MagicMock()
        self._run_backfill(["prog"], tmp_path, mock_s3)

        assert mock_s3.upload_file.call_count == 3  # 2 faces + 1 exemplar

        uploaded_keys = [call[0][1] for call in mock_s3.upload_file.call_args_list]
        face_keys = [k for k in uploaded_keys if "/faces/exemplars/" not in k]
        exemplar_keys = [k for k in uploaded_keys if "/faces/exemplars/" in k]
        assert len(face_keys) == 2
        assert len(exemplar_keys) == 1

    def test_backfill_skip_existing(self, tmp_path: Path):
        """With --skip-existing, should skip S3 keys that already exist."""
        org_id = str(uuid4())
        face_dir = tmp_path / org_id / "faces"
        face_dir.mkdir(parents=True)
        (face_dir / "person-1.jpg").write_bytes(b"\xff\xd8\xff\xd9")

        mock_s3 = MagicMock()
        mock_s3.exists.return_value = True

        self._run_backfill(["prog", "--skip-existing"], tmp_path, mock_s3)
        mock_s3.upload_file.assert_not_called()

    def test_backfill_handles_upload_error_gracefully(self, tmp_path: Path):
        """Backfill should continue on upload error."""
        org_id = str(uuid4())
        face_dir = tmp_path / org_id / "faces"
        face_dir.mkdir(parents=True)
        (face_dir / "person-1.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        (face_dir / "person-2.jpg").write_bytes(b"\xff\xd8\xff\xd9")

        mock_s3 = MagicMock()
        mock_s3.upload_file.side_effect = [Exception("S3 error"), None]

        self._run_backfill(["prog"], tmp_path, mock_s3)
        assert mock_s3.upload_file.call_count == 2

    def test_backfill_empty_directory(self, tmp_path: Path):
        """Backfill on empty thumbnail directory should complete without error."""
        mock_s3 = MagicMock()
        self._run_backfill(["prog"], tmp_path, mock_s3)
        mock_s3.upload_file.assert_not_called()
