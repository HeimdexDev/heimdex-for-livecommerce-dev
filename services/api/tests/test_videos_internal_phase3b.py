"""Tests for the Phase 3b internal endpoints used by the
shorts-auto product mode v2 track worker:

* ``POST /internal/videos/{file_id}/scenes-by-visual-similarity``
* ``POST /internal/videos/{file_id}/scenes-content``

Both are mounted on the existing ``videos`` internal router (gated
behind ``drive_connector_enabled`` in main.py — same gate as the
Phase 2.5a ``scenes-with-keyframes`` endpoint they sit alongside).
Tests build a minimal app with mocked dependencies so logic is
testable without OpenSearch / DB / Drive subsystem booted.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.videos.internal_router import router as internal_router


def _drive_file(*, file_id: UUID, video_id: str = "gd_abc"):
    obj = MagicMock()
    obj.id = file_id
    obj.video_id = video_id
    return obj


def _build_app(
    *,
    drive_file_obj,
    scene_client_mock: MagicMock | None = None,
    internal_token: str = "test-internal-token",
) -> FastAPI:
    """Mirror of the Phase 2.5a test helper. ``scene_client_mock``
    can be pre-loaded with method stubs (``search_visual_vector_in_video``,
    ``mget_scenes``) for the endpoint under test.
    """
    from app.dependencies import (
        get_db_session,
        get_scene_opensearch_client,
        verify_internal_token,
    )

    fake_repo = MagicMock()
    fake_repo.get_by_id = AsyncMock(return_value=drive_file_obj)
    import app.modules.drive.repository as drive_repo_module
    drive_repo_module.DriveFileRepository = MagicMock(return_value=fake_repo)  # type: ignore[assignment]

    if scene_client_mock is None:
        scene_client_mock = MagicMock()
    # The endpoint reads VISUAL_EMBEDDING_DIMENSION off the client to
    # validate query_vec length — match the prod constant.
    scene_client_mock.VISUAL_EMBEDDING_DIMENSION = 768

    app = FastAPI()
    app.include_router(internal_router, prefix="/internal")
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()
    app.dependency_overrides[get_scene_opensearch_client] = lambda: scene_client_mock
    app.dependency_overrides[verify_internal_token] = lambda: internal_token

    return app


def _vec(dim: int = 768, fill: float = 0.01) -> list[float]:
    return [fill] * dim


# =====================================================================
# /scenes-by-visual-similarity
# =====================================================================


def test_visual_similarity_returns_top_k_above_threshold_sorted_by_score():
    file_id = uuid4()
    org_id = uuid4()
    drive_file = _drive_file(file_id=file_id, video_id="gd_xyz")

    # OS hits — 3 above threshold, 1 below; endpoint must drop the
    # below-threshold one and return the rest in OS order (already
    # sorted desc by _score).
    scene_client = MagicMock()
    scene_client.search_visual_vector_in_video = AsyncMock(
        return_value=[
            {"_score": 0.91, "_source": {"scene_id": "gd_xyz_scene_007"}},
            {"_score": 0.74, "_source": {"scene_id": "gd_xyz_scene_012"}},
            {"_score": 0.55, "_source": {"scene_id": "gd_xyz_scene_003"}},
            {"_score": 0.30, "_source": {"scene_id": "gd_xyz_scene_099"}},
        ]
    )
    app = _build_app(drive_file_obj=drive_file, scene_client_mock=scene_client)

    with TestClient(app) as client:
        resp = client.post(
            f"/internal/videos/{file_id}/scenes-by-visual-similarity",
            json={"query_vec": _vec(), "top_k": 60, "min_similarity": 0.5},
            headers={
                "Authorization": "Bearer test-internal-token",
                "X-Heimdex-Org-Id": str(org_id),
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["video_id"] == "gd_xyz"
    assert [s["scene_id"] for s in body["scenes"]] == [
        "gd_xyz_scene_007",
        "gd_xyz_scene_012",
        "gd_xyz_scene_003",
    ]
    assert body["scenes"][0]["similarity"] == pytest.approx(0.91)


def test_visual_similarity_passes_video_id_org_id_size_to_client():
    file_id = uuid4()
    org_id = uuid4()
    drive_file = _drive_file(file_id=file_id, video_id="gd_v")

    captured: dict[str, Any] = {}

    async def _capture(**kwargs):
        captured.update(kwargs)
        return []

    scene_client = MagicMock()
    scene_client.search_visual_vector_in_video = _capture
    app = _build_app(drive_file_obj=drive_file, scene_client_mock=scene_client)

    with TestClient(app) as client:
        client.post(
            f"/internal/videos/{file_id}/scenes-by-visual-similarity",
            json={"query_vec": _vec(), "top_k": 17, "min_similarity": 0.0},
            headers={
                "Authorization": "Bearer test-internal-token",
                "X-Heimdex-Org-Id": str(org_id),
            },
        )

    assert captured["video_id"] == "gd_v"
    assert captured["org_id"] == str(org_id)
    assert captured["size"] == 17
    assert len(captured["visual_embedding"]) == 768


@pytest.mark.parametrize(
    "vec,expected_msg",
    [
        ([0.0] * 100, "768"),  # wrong dimension — message references prod dim
        ([], "non-empty"),  # empty
        ("not-a-list", "list"),  # wrong type
    ],
)
def test_visual_similarity_400_on_invalid_query_vec(vec, expected_msg):
    file_id = uuid4()
    drive_file = _drive_file(file_id=file_id)
    app = _build_app(drive_file_obj=drive_file)
    with TestClient(app) as client:
        resp = client.post(
            f"/internal/videos/{file_id}/scenes-by-visual-similarity",
            json={"query_vec": vec, "top_k": 10, "min_similarity": 0.5},
            headers={
                "Authorization": "Bearer test-internal-token",
                "X-Heimdex-Org-Id": str(uuid4()),
            },
        )
    assert resp.status_code == 400
    assert expected_msg in resp.json()["detail"]


@pytest.mark.parametrize(
    "top_k",
    [0, -1, 201, 10000],
)
def test_visual_similarity_400_on_invalid_top_k(top_k):
    file_id = uuid4()
    drive_file = _drive_file(file_id=file_id)
    app = _build_app(drive_file_obj=drive_file)
    with TestClient(app) as client:
        resp = client.post(
            f"/internal/videos/{file_id}/scenes-by-visual-similarity",
            json={"query_vec": _vec(), "top_k": top_k, "min_similarity": 0.5},
            headers={
                "Authorization": "Bearer test-internal-token",
                "X-Heimdex-Org-Id": str(uuid4()),
            },
        )
    assert resp.status_code == 400
    assert "top_k" in resp.json()["detail"]


@pytest.mark.parametrize("min_sim", [-0.01, 1.01, 5.0])
def test_visual_similarity_400_on_invalid_min_similarity(min_sim):
    file_id = uuid4()
    drive_file = _drive_file(file_id=file_id)
    app = _build_app(drive_file_obj=drive_file)
    with TestClient(app) as client:
        resp = client.post(
            f"/internal/videos/{file_id}/scenes-by-visual-similarity",
            json={"query_vec": _vec(), "top_k": 10, "min_similarity": min_sim},
            headers={
                "Authorization": "Bearer test-internal-token",
                "X-Heimdex-Org-Id": str(uuid4()),
            },
        )
    assert resp.status_code == 400
    assert "min_similarity" in resp.json()["detail"]


def test_visual_similarity_404_when_drive_file_missing():
    file_id = uuid4()
    app = _build_app(drive_file_obj=None)
    with TestClient(app) as client:
        resp = client.post(
            f"/internal/videos/{file_id}/scenes-by-visual-similarity",
            json={"query_vec": _vec(), "top_k": 10, "min_similarity": 0.0},
            headers={
                "Authorization": "Bearer test-internal-token",
                "X-Heimdex-Org-Id": str(uuid4()),
            },
        )
    assert resp.status_code == 404


def test_visual_similarity_400_on_invalid_org_id_header():
    file_id = uuid4()
    drive_file = _drive_file(file_id=file_id)
    app = _build_app(drive_file_obj=drive_file)
    with TestClient(app) as client:
        resp = client.post(
            f"/internal/videos/{file_id}/scenes-by-visual-similarity",
            json={"query_vec": _vec(), "top_k": 10, "min_similarity": 0.0},
            headers={
                "Authorization": "Bearer test-internal-token",
                "X-Heimdex-Org-Id": "not-a-uuid",
            },
        )
    assert resp.status_code == 400


def test_visual_similarity_drops_hits_with_missing_scene_id():
    """OS doc with no scene_id field is silently skipped — defensive
    against schema drift / partial reads."""
    file_id = uuid4()
    drive_file = _drive_file(file_id=file_id, video_id="gd_x")

    scene_client = MagicMock()
    scene_client.search_visual_vector_in_video = AsyncMock(
        return_value=[
            {"_score": 0.9, "_source": {"scene_id": "gd_x_scene_1"}},
            {"_score": 0.8, "_source": {}},  # missing scene_id
            {"_score": 0.7, "_source": {"scene_id": "gd_x_scene_2"}},
        ]
    )
    app = _build_app(drive_file_obj=drive_file, scene_client_mock=scene_client)

    with TestClient(app) as client:
        resp = client.post(
            f"/internal/videos/{file_id}/scenes-by-visual-similarity",
            json={"query_vec": _vec(), "top_k": 10, "min_similarity": 0.0},
            headers={
                "Authorization": "Bearer test-internal-token",
                "X-Heimdex-Org-Id": str(uuid4()),
            },
        )
    assert resp.status_code == 200
    assert [s["scene_id"] for s in resp.json()["scenes"]] == [
        "gd_x_scene_1",
        "gd_x_scene_2",
    ]


def test_visual_similarity_empty_results_returns_200_with_zero_scenes():
    file_id = uuid4()
    drive_file = _drive_file(file_id=file_id, video_id="gd_a")
    scene_client = MagicMock()
    scene_client.search_visual_vector_in_video = AsyncMock(return_value=[])
    app = _build_app(drive_file_obj=drive_file, scene_client_mock=scene_client)

    with TestClient(app) as client:
        resp = client.post(
            f"/internal/videos/{file_id}/scenes-by-visual-similarity",
            json={"query_vec": _vec(), "top_k": 10, "min_similarity": 0.5},
            headers={
                "Authorization": "Bearer test-internal-token",
                "X-Heimdex-Org-Id": str(uuid4()),
            },
        )
    assert resp.status_code == 200
    assert resp.json()["scenes"] == []


def test_visual_similarity_requires_bearer_token():
    file_id = uuid4()
    drive_file = _drive_file(file_id=file_id)
    app = _build_app(drive_file_obj=drive_file)
    from app.dependencies import verify_internal_token
    app.dependency_overrides.pop(verify_internal_token, None)

    with TestClient(app) as client:
        resp = client.post(
            f"/internal/videos/{file_id}/scenes-by-visual-similarity",
            json={"query_vec": _vec(), "top_k": 10, "min_similarity": 0.0},
            headers={"X-Heimdex-Org-Id": str(uuid4())},
        )
    assert resp.status_code in (401, 403, 422)


# =====================================================================
# /scenes-content
# =====================================================================


def test_scenes_content_returns_per_scene_transcript_and_ocr():
    file_id = uuid4()
    org_id = uuid4()
    drive_file = _drive_file(file_id=file_id, video_id="gd_xyz")

    scene_client = MagicMock()
    scene_client.mget_scenes = AsyncMock(
        return_value={
            f"{org_id}:gd_xyz_scene_007": {
                "scene_id": "gd_xyz_scene_007",
                "video_id": "gd_xyz",
                "start_ms": 5000,
                "end_ms": 10000,
                "transcript_raw": "이 cosmetics is great",
                "speaker_transcript": "[Host] 이 cosmetics is great",
                "ocr_text_raw": "PROMOTION",
            },
            f"{org_id}:gd_xyz_scene_012": {
                "scene_id": "gd_xyz_scene_012",
                "video_id": "gd_xyz",
                "start_ms": 15000,
                "end_ms": 18000,
                "transcript_raw": "",
                "speaker_transcript": "",
                "ocr_text_raw": "",
            },
        }
    )
    app = _build_app(drive_file_obj=drive_file, scene_client_mock=scene_client)

    with TestClient(app) as client:
        resp = client.post(
            f"/internal/videos/{file_id}/scenes-content",
            json={"scene_ids": ["gd_xyz_scene_007", "gd_xyz_scene_012"]},
            headers={
                "Authorization": "Bearer test-internal-token",
                "X-Heimdex-Org-Id": str(org_id),
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["video_id"] == "gd_xyz"
    assert len(body["scenes"]) == 2

    s7 = next(s for s in body["scenes"] if s["scene_id"] == "gd_xyz_scene_007")
    assert s7["start_ms"] == 5000
    assert s7["end_ms"] == 10000
    assert s7["transcript_raw"] == "이 cosmetics is great"
    assert s7["ocr_text_raw"] == "PROMOTION"

    # Second scene — empty fields preserved as empty strings (not null).
    s12 = next(s for s in body["scenes"] if s["scene_id"] == "gd_xyz_scene_012")
    assert s12["transcript_raw"] == ""
    assert s12["ocr_text_raw"] == ""


def test_scenes_content_drops_scene_belonging_to_other_video():
    """Defense in depth: a scene_id from another video on the same
    org must NOT be returned even if the doc_id mget happens to find
    it. Filter by video_id post-mget."""
    file_id = uuid4()
    org_id = uuid4()
    drive_file = _drive_file(file_id=file_id, video_id="gd_correct")

    scene_client = MagicMock()
    scene_client.mget_scenes = AsyncMock(
        return_value={
            f"{org_id}:gd_correct_scene_001": {
                "scene_id": "gd_correct_scene_001",
                "video_id": "gd_correct",
                "start_ms": 0,
                "end_ms": 1000,
                "transcript_raw": "ok",
                "speaker_transcript": "",
                "ocr_text_raw": "",
            },
            f"{org_id}:gd_other_scene_001": {
                "scene_id": "gd_other_scene_001",
                "video_id": "gd_other",  # <-- different video
                "start_ms": 0,
                "end_ms": 1000,
                "transcript_raw": "should be dropped",
                "speaker_transcript": "",
                "ocr_text_raw": "",
            },
        }
    )
    app = _build_app(drive_file_obj=drive_file, scene_client_mock=scene_client)

    with TestClient(app) as client:
        resp = client.post(
            f"/internal/videos/{file_id}/scenes-content",
            json={
                "scene_ids": [
                    "gd_correct_scene_001",
                    "gd_other_scene_001",
                ],
            },
            headers={
                "Authorization": "Bearer test-internal-token",
                "X-Heimdex-Org-Id": str(org_id),
            },
        )
    assert resp.status_code == 200
    scenes = resp.json()["scenes"]
    assert len(scenes) == 1
    assert scenes[0]["scene_id"] == "gd_correct_scene_001"


def test_scenes_content_passes_org_scoped_doc_ids_to_mget():
    file_id = uuid4()
    org_id = uuid4()
    drive_file = _drive_file(file_id=file_id, video_id="gd_v")

    captured: dict[str, list[str]] = {}

    async def _capture(doc_ids):
        captured["doc_ids"] = doc_ids
        return {}

    scene_client = MagicMock()
    scene_client.mget_scenes = _capture
    app = _build_app(drive_file_obj=drive_file, scene_client_mock=scene_client)

    with TestClient(app) as client:
        client.post(
            f"/internal/videos/{file_id}/scenes-content",
            json={"scene_ids": ["gd_v_scene_001", "gd_v_scene_002"]},
            headers={
                "Authorization": "Bearer test-internal-token",
                "X-Heimdex-Org-Id": str(org_id),
            },
        )

    assert captured["doc_ids"] == [
        f"{org_id}:gd_v_scene_001",
        f"{org_id}:gd_v_scene_002",
    ]


def test_scenes_content_skips_missing_scene_ids():
    """A scene_id requested but not returned by mget (e.g., deleted
    or cross-org) is simply absent from the response."""
    file_id = uuid4()
    org_id = uuid4()
    drive_file = _drive_file(file_id=file_id, video_id="gd_v")

    scene_client = MagicMock()
    scene_client.mget_scenes = AsyncMock(
        return_value={
            f"{org_id}:gd_v_scene_001": {
                "scene_id": "gd_v_scene_001",
                "video_id": "gd_v",
                "start_ms": 0,
                "end_ms": 1000,
                "transcript_raw": "x",
                "speaker_transcript": "",
                "ocr_text_raw": "",
            },
        }
    )
    app = _build_app(drive_file_obj=drive_file, scene_client_mock=scene_client)

    with TestClient(app) as client:
        resp = client.post(
            f"/internal/videos/{file_id}/scenes-content",
            json={
                "scene_ids": [
                    "gd_v_scene_001",
                    "gd_v_scene_does_not_exist",
                ],
            },
            headers={
                "Authorization": "Bearer test-internal-token",
                "X-Heimdex-Org-Id": str(org_id),
            },
        )
    assert resp.status_code == 200
    scenes = resp.json()["scenes"]
    assert [s["scene_id"] for s in scenes] == ["gd_v_scene_001"]


def test_scenes_content_400_on_non_list_scene_ids():
    file_id = uuid4()
    drive_file = _drive_file(file_id=file_id)
    app = _build_app(drive_file_obj=drive_file)
    with TestClient(app) as client:
        resp = client.post(
            f"/internal/videos/{file_id}/scenes-content",
            json={"scene_ids": "not-a-list"},
            headers={
                "Authorization": "Bearer test-internal-token",
                "X-Heimdex-Org-Id": str(uuid4()),
            },
        )
    assert resp.status_code == 400


def test_scenes_content_400_on_too_many_scene_ids():
    file_id = uuid4()
    drive_file = _drive_file(file_id=file_id)
    app = _build_app(drive_file_obj=drive_file)
    with TestClient(app) as client:
        resp = client.post(
            f"/internal/videos/{file_id}/scenes-content",
            json={"scene_ids": [f"gd_v_scene_{i:03d}" for i in range(201)]},
            headers={
                "Authorization": "Bearer test-internal-token",
                "X-Heimdex-Org-Id": str(uuid4()),
            },
        )
    assert resp.status_code == 400
    assert "200" in resp.json()["detail"]


def test_scenes_content_400_on_non_string_scene_id():
    file_id = uuid4()
    drive_file = _drive_file(file_id=file_id)
    app = _build_app(drive_file_obj=drive_file)
    with TestClient(app) as client:
        resp = client.post(
            f"/internal/videos/{file_id}/scenes-content",
            json={"scene_ids": ["valid_id", 123]},
            headers={
                "Authorization": "Bearer test-internal-token",
                "X-Heimdex-Org-Id": str(uuid4()),
            },
        )
    assert resp.status_code == 400


def test_scenes_content_404_when_drive_file_missing():
    file_id = uuid4()
    app = _build_app(drive_file_obj=None)
    with TestClient(app) as client:
        resp = client.post(
            f"/internal/videos/{file_id}/scenes-content",
            json={"scene_ids": ["gd_v_scene_001"]},
            headers={
                "Authorization": "Bearer test-internal-token",
                "X-Heimdex-Org-Id": str(uuid4()),
            },
        )
    assert resp.status_code == 404


def test_scenes_content_empty_scene_ids_returns_empty_list():
    file_id = uuid4()
    org_id = uuid4()
    drive_file = _drive_file(file_id=file_id, video_id="gd_v")

    scene_client = MagicMock()
    scene_client.mget_scenes = AsyncMock(return_value={})
    app = _build_app(drive_file_obj=drive_file, scene_client_mock=scene_client)

    with TestClient(app) as client:
        resp = client.post(
            f"/internal/videos/{file_id}/scenes-content",
            json={"scene_ids": []},
            headers={
                "Authorization": "Bearer test-internal-token",
                "X-Heimdex-Org-Id": str(org_id),
            },
        )
    assert resp.status_code == 200
    assert resp.json()["scenes"] == []


def test_scenes_content_requires_bearer_token():
    file_id = uuid4()
    drive_file = _drive_file(file_id=file_id)
    app = _build_app(drive_file_obj=drive_file)
    from app.dependencies import verify_internal_token
    app.dependency_overrides.pop(verify_internal_token, None)

    with TestClient(app) as client:
        resp = client.post(
            f"/internal/videos/{file_id}/scenes-content",
            json={"scene_ids": ["gd_v_scene_001"]},
            headers={"X-Heimdex-Org-Id": str(uuid4())},
        )
    assert resp.status_code in (401, 403, 422)
