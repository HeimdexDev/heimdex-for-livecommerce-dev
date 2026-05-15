"""Integration tests for highlight reel API endpoints.

Uses mocked SceneDataPort to avoid OpenSearch dependency.
Tests the full request/response cycle through FastAPI.
"""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.modules.auth import get_current_user
from app.modules.highlight_reel.domain import SceneRecord
from app.modules.highlight_reel.schemas import HighlightClipPreview
from app.modules.highlight_reel.service import HighlightReelService
from app.modules.tenancy import OrgContext, get_current_org


# ---------------------------------------------------------------------------
# Fixtures
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


_ORG_CTX = OrgContext(org_id=uuid4(), org_slug="devorg")
_USER = MagicMock()
_USER.id = uuid4()


def _consecutive_scenes(video_id: str, count: int, duration_ms: int = 45000) -> list[SceneRecord]:
    scenes = []
    cursor = 0
    for i in range(count):
        scenes.append(SceneRecord(f"{video_id}_s{i}", video_id, cursor, cursor + duration_ms))
        cursor += duration_ms
    return scenes


def _mock_adapter(scenes, excluded=None, titles=None):
    adapter = MagicMock()
    adapter.get_person_scenes = AsyncMock(return_value=scenes)
    adapter.get_excluded_video_ids = AsyncMock(return_value=excluded or [])
    video_ids = {s.video_id for s in scenes}
    adapter.get_video_titles = AsyncMock(return_value=titles or {vid: f"Video {vid}" for vid in video_ids})
    return adapter


_SETTINGS_PATCH = patch(
    "app.modules.highlight_reel.router.get_settings",
    return_value=MagicMock(people_enabled=True, highlight_reel_enabled=True),
)


def _setup_overrides():
    from app.dependencies import (
        get_db_session,
        get_people_video_exclusion_repository,
        get_scene_opensearch_client,
        get_shorts_render_service,
    )

    async def _mock_org():
        return _ORG_CTX

    async def _mock_user():
        return _USER

    app.dependency_overrides[get_current_org] = _mock_org
    app.dependency_overrides[get_current_user] = _mock_user
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()
    app.dependency_overrides[get_scene_opensearch_client] = lambda: MagicMock()
    app.dependency_overrides[get_people_video_exclusion_repository] = lambda: MagicMock()
    _SETTINGS_PATCH.start()


def _clear_overrides():
    _SETTINGS_PATCH.stop()
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Preview endpoint
# ---------------------------------------------------------------------------

class TestHighlightReelPreview:
    def test_preview_returns_clips(self):
        _setup_overrides()
        scenes = [*_consecutive_scenes("v1", 5), *_consecutive_scenes("v2", 3)]
        adapter = _mock_adapter(scenes)
        sp = _startup_patches()
        try:
            with sp[0], sp[1], sp[2], sp[3], sp[4], sp[5], sp[6]:
                with patch("app.modules.highlight_reel.router.OpenSearchSceneDataAdapter", return_value=adapter):
                    with TestClient(app) as client:
                        resp = client.post(
                            "/api/people/person_test/highlight-reel/preview",
                            json={"target_duration_s": 60},
                            headers={"host": "devorg.app.heimdex.local"},
                        )
            assert resp.status_code == 200
            data = resp.json()
            assert data["person_cluster_id"] == "person_test"
            assert len(data["clips"]) > 0
            assert data["total_duration_ms"] <= 60000
            assert data["videos_used"] >= 1
        finally:
            _clear_overrides()

    def test_preview_maximizes_video_diversity(self):
        _setup_overrides()
        scenes = []
        for i in range(5):
            scenes.extend(_consecutive_scenes(f"v{i}", 3))
        adapter = _mock_adapter(scenes)
        sp = _startup_patches()
        try:
            with sp[0], sp[1], sp[2], sp[3], sp[4], sp[5], sp[6]:
                with patch("app.modules.highlight_reel.router.OpenSearchSceneDataAdapter", return_value=adapter):
                    with TestClient(app) as client:
                        resp = client.post(
                            "/api/people/person_test/highlight-reel/preview",
                            json={"target_duration_s": 120},
                            headers={"host": "devorg.app.heimdex.local"},
                        )
            data = resp.json()
            video_ids = {c["video_id"] for c in data["clips"]}
            assert len(video_ids) >= 3
        finally:
            _clear_overrides()

    def test_preview_respects_exclusions(self):
        _setup_overrides()
        scenes = [*_consecutive_scenes("v1", 5), *_consecutive_scenes("v2", 5)]
        adapter = _mock_adapter(scenes, excluded=["v1"])
        sp = _startup_patches()
        try:
            with sp[0], sp[1], sp[2], sp[3], sp[4], sp[5], sp[6]:
                with patch("app.modules.highlight_reel.router.OpenSearchSceneDataAdapter", return_value=adapter):
                    with TestClient(app) as client:
                        resp = client.post(
                            "/api/people/person_test/highlight-reel/preview",
                            json={"target_duration_s": 60},
                            headers={"host": "devorg.app.heimdex.local"},
                        )
            data = resp.json()
            assert all(c["video_id"] != "v1" for c in data["clips"])
            assert data["videos_excluded"] == 1
        finally:
            _clear_overrides()

    def test_preview_422_when_no_scenes(self):
        _setup_overrides()
        adapter = _mock_adapter([])
        sp = _startup_patches()
        try:
            with sp[0], sp[1], sp[2], sp[3], sp[4], sp[5], sp[6]:
                with patch("app.modules.highlight_reel.router.OpenSearchSceneDataAdapter", return_value=adapter):
                    with TestClient(app) as client:
                        resp = client.post(
                            "/api/people/person_test/highlight-reel/preview",
                            json={"target_duration_s": 60},
                            headers={"host": "devorg.app.heimdex.local"},
                        )
            assert resp.status_code == 422
        finally:
            _clear_overrides()

    def test_preview_validates_duration_bounds(self):
        _setup_overrides()
        sp = _startup_patches()
        try:
            with sp[0], sp[1], sp[2], sp[3], sp[4], sp[5], sp[6]:
                with TestClient(app) as client:
                    resp = client.post(
                        "/api/people/p/highlight-reel/preview",
                        json={"target_duration_s": 5},
                        headers={"host": "devorg.app.heimdex.local"},
                    )
                    assert resp.status_code == 422

                    resp = client.post(
                        "/api/people/p/highlight-reel/preview",
                        json={"target_duration_s": 600},
                        headers={"host": "devorg.app.heimdex.local"},
                    )
                    assert resp.status_code == 422
        finally:
            _clear_overrides()

    def test_preview_clips_have_video_titles(self):
        _setup_overrides()
        scenes = _consecutive_scenes("v1", 3)
        adapter = _mock_adapter(scenes, titles={"v1": "라이브쇼핑 #42"})
        sp = _startup_patches()
        try:
            with sp[0], sp[1], sp[2], sp[3], sp[4], sp[5], sp[6]:
                with patch("app.modules.highlight_reel.router.OpenSearchSceneDataAdapter", return_value=adapter):
                    with TestClient(app) as client:
                        resp = client.post(
                            "/api/people/person_test/highlight-reel/preview",
                            json={"target_duration_s": 60},
                            headers={"host": "devorg.app.heimdex.local"},
                        )
            data = resp.json()
            assert data["clips"][0]["video_title"] == "라이브쇼핑 #42"
        finally:
            _clear_overrides()

    def test_preview_timeline_non_overlapping(self):
        _setup_overrides()
        scenes = []
        for i in range(4):
            scenes.extend(_consecutive_scenes(f"v{i}", 5))
        adapter = _mock_adapter(scenes)
        sp = _startup_patches()
        try:
            with sp[0], sp[1], sp[2], sp[3], sp[4], sp[5], sp[6]:
                with patch("app.modules.highlight_reel.router.OpenSearchSceneDataAdapter", return_value=adapter):
                    with TestClient(app) as client:
                        resp = client.post(
                            "/api/people/person_test/highlight-reel/preview",
                            json={"target_duration_s": 120},
                            headers={"host": "devorg.app.heimdex.local"},
                        )
            clips = resp.json()["clips"]
            for i in range(1, len(clips)):
                prev_end = clips[i - 1]["timeline_start_ms"] + clips[i - 1]["duration_ms"]
                assert clips[i]["timeline_start_ms"] == prev_end
        finally:
            _clear_overrides()


# ---------------------------------------------------------------------------
# Render endpoint
# ---------------------------------------------------------------------------

class TestHighlightReelRender:
    def test_render_creates_job(self):
        _setup_overrides()

        mock_render_service = MagicMock()
        mock_result = MagicMock()
        mock_result.id = uuid4()
        mock_result.video_id = "highlight:person_test"
        mock_result.title = "Highlight: person_test"
        mock_result.status = "queued"
        mock_result.created_at = "2026-04-01T12:00:00"
        mock_result.completed_at = None
        mock_result.render_time_ms = None
        mock_result.output_duration_ms = None
        mock_result.output_size_bytes = None
        mock_result.error = None
        mock_result.download_url = None
        mock_render_service.create_render_job = AsyncMock(return_value=mock_result)

        from app.dependencies import get_shorts_render_service
        app.dependency_overrides[get_shorts_render_service] = lambda: mock_render_service

        sp = _startup_patches()
        try:
            with sp[0], sp[1], sp[2], sp[3], sp[4], sp[5], sp[6]:
                with TestClient(app) as client:
                    resp = client.post(
                        "/api/people/person_test/highlight-reel/render",
                        json={
                            "clips": [{
                                "video_id": "v1", "video_title": "Test", "scene_id": "s1",
                                "start_ms": 0, "end_ms": 30000, "timeline_start_ms": 0,
                                "duration_ms": 30000, "run_scene_count": 1,
                            }],
                            "title": "My Highlight",
                        },
                        headers={"host": "devorg.app.heimdex.local"},
                    )

            assert resp.status_code == 200
            mock_render_service.create_render_job.assert_called_once()
        finally:
            _clear_overrides()

    def test_render_422_when_no_clips(self):
        _setup_overrides()
        sp = _startup_patches()
        try:
            with sp[0], sp[1], sp[2], sp[3], sp[4], sp[5], sp[6]:
                with TestClient(app) as client:
                    resp = client.post(
                        "/api/people/person_test/highlight-reel/render",
                        json={"clips": []},
                        headers={"host": "devorg.app.heimdex.local"},
                    )
            assert resp.status_code == 422
        finally:
            _clear_overrides()


# ---------------------------------------------------------------------------
# Composition dict tests (unit-level, no HTTP)
# ---------------------------------------------------------------------------

class TestBuildCompositionDict:
    def test_composition_structure(self):
        clips = [
            HighlightClipPreview(
                video_id="v1", video_title="Test", scene_id="s1",
                start_ms=0, end_ms=30000, timeline_start_ms=0,
                duration_ms=30000, run_scene_count=2,
            ),
            HighlightClipPreview(
                video_id="v2", video_title="Test2", scene_id="s2",
                start_ms=10000, end_ms=40000, timeline_start_ms=30000,
                duration_ms=30000, run_scene_count=1,
            ),
        ]
        comp = HighlightReelService.build_composition_dict(clips)
        assert comp["output"]["width"] == 1280
        assert comp["output"]["height"] == 720
        assert len(comp["scene_clips"]) == 2
        assert comp["scene_clips"][0]["timeline_start_ms"] == 0
        assert comp["scene_clips"][1]["timeline_start_ms"] == 30000
        assert comp["subtitles"] == []

    def test_composition_timeline_sequential(self):
        clips = [
            HighlightClipPreview(
                video_id="v1", scene_id="s1", start_ms=0, end_ms=20000,
                timeline_start_ms=0, duration_ms=20000, run_scene_count=1,
            ),
            HighlightClipPreview(
                video_id="v2", scene_id="s2", start_ms=5000, end_ms=25000,
                timeline_start_ms=20000, duration_ms=20000, run_scene_count=1,
            ),
        ]
        comp = HighlightReelService.build_composition_dict(clips)
        assert comp["scene_clips"][0]["timeline_start_ms"] == 0
        assert comp["scene_clips"][1]["timeline_start_ms"] == 20000
