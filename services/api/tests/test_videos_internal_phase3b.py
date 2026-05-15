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


def _drive_file(*, file_id: UUID, video_id: str = "gd_abc", org_id: UUID | None = None):
    """Mocked DriveFile row. Pattern B endpoints derive ``org_id``
    from the resource itself, so the test fixture must populate
    ``obj.org_id`` (not just rely on the asserted header)."""
    obj = MagicMock()
    obj.id = file_id
    obj.video_id = video_id
    obj.org_id = org_id if org_id is not None else uuid4()
    return obj


@pytest.fixture
def _build_app(monkeypatch):
    """Mirror of the Phase 2.5a test helper. ``scene_client_mock``
    can be pre-loaded with method stubs (``search_visual_vector_in_video``,
    ``mget_scenes``) for the endpoint under test.

    Uses pytest's ``monkeypatch`` so the ``DriveFileRepository``
    module-attribute override auto-reverts between tests — critical
    so the patch doesn't bleed into other test files (e.g.,
    ``test_internal_drive_router.py``) that import the real class.
    """

    def _factory(
        *,
        drive_file_obj,
        scene_client_mock: MagicMock | None = None,
        internal_token: str = "test-internal-token",
    ) -> FastAPI:
        from app.dependencies import (
            get_db_session,
            get_scene_opensearch_client,
            verify_internal_token,
        )

        fake_repo = MagicMock()
        # Pattern B (post-2026-05-01): endpoints look up DriveFile
        # by id alone via ``get_by_id_resource_scoped`` and derive
        # ``org_id`` from the resource. Mock both the new method and
        # ``get_by_id`` for back-compat.
        fake_repo.get_by_id_resource_scoped = AsyncMock(return_value=drive_file_obj)
        fake_repo.get_by_id = AsyncMock(return_value=drive_file_obj)

        import app.modules.drive.repository as drive_repo_module
        monkeypatch.setattr(
            drive_repo_module,
            "DriveFileRepository",
            MagicMock(return_value=fake_repo),
        )

        if scene_client_mock is None:
            scene_client_mock = MagicMock()
        scene_client_mock.VISUAL_EMBEDDING_DIMENSION = 768

        app = FastAPI()
        app.include_router(internal_router, prefix="/internal")
        app.dependency_overrides[get_db_session] = lambda: AsyncMock()
        app.dependency_overrides[get_scene_opensearch_client] = lambda: scene_client_mock
        app.dependency_overrides[verify_internal_token] = lambda: internal_token

        return app

    return _factory


def _vec(dim: int = 768, fill: float = 0.01) -> list[float]:
    return [fill] * dim


# =====================================================================
# /scenes-by-visual-similarity
# =====================================================================


def test_visual_similarity_returns_top_k_above_threshold_sorted_by_score(_build_app):
    file_id = uuid4()
    org_id = uuid4()
    drive_file = _drive_file(file_id=file_id, video_id="gd_xyz", org_id=org_id)

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


def test_visual_similarity_passes_video_id_org_id_size_to_client(_build_app):
    file_id = uuid4()
    org_id = uuid4()
    drive_file = _drive_file(file_id=file_id, video_id="gd_v", org_id=org_id)

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


def _vec_with_string_at(idx: int) -> str:
    """Build a JSON string body where one element of query_vec is a
    string. Python's httpx (used by TestClient) serializes JSON
    client-side and rejects NaN / inf literals — so for these
    adversarial cases we craft the raw JSON body and bypass the
    serializer via TestClient's ``content=`` parameter. NaN / inf
    are non-standard JSON but Python's ``json.loads`` accepts them
    by default, which matches what Starlette / FastAPI receive."""
    elems = [str(0.01)] * 768
    elems[idx] = '"x"'
    return (
        '{"query_vec": [' + ", ".join(elems) + '], '
        '"top_k": 10, "min_similarity": 0.0}'
    )


def _vec_with_token_at(idx: int, token: str) -> str:
    """Build a raw JSON body with a non-standard JSON token (NaN,
    Infinity, -Infinity, true, null) at ``idx``."""
    elems = [str(0.01)] * 768
    elems[idx] = token
    return (
        '{"query_vec": [' + ", ".join(elems) + '], '
        '"top_k": 10, "min_similarity": 0.0}'
    )


@pytest.mark.parametrize(
    "body_factory,expected_index",
    [
        # String element at index 0
        (lambda: _vec_with_string_at(0), 0),
        # Boolean element at index 5 (bool is subclass of int in Python — must be excluded explicitly)
        (lambda: _vec_with_token_at(5, "true"), 5),
        # NaN at index 100
        (lambda: _vec_with_token_at(100, "NaN"), 100),
        # +Infinity at index 200
        (lambda: _vec_with_token_at(200, "Infinity"), 200),
        # -Infinity at index 300
        (lambda: _vec_with_token_at(300, "-Infinity"), 300),
        # null
        (lambda: _vec_with_token_at(0, "null"), 0),
    ],
)
def test_visual_similarity_400_on_non_finite_query_vec_element(
    body_factory, expected_index, _build_app
):
    """Codex F3: per-element validation. Length-only validation lets
    strings / bools / NaN / inf reach OpenSearch unchanged — best case
    500 on serialization, worst case 200 with undefined ranking. The
    endpoint must reject these explicitly with a 400 that names the
    bad index."""
    file_id = uuid4()
    drive_file = _drive_file(file_id=file_id)
    app = _build_app(drive_file_obj=drive_file)
    with TestClient(app) as client:
        resp = client.post(
            f"/internal/videos/{file_id}/scenes-by-visual-similarity",
            content=body_factory(),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer test-internal-token",
                "X-Heimdex-Org-Id": str(uuid4()),
            },
        )
    assert resp.status_code == 400
    assert f"query_vec[{expected_index}]" in resp.json()["detail"]


@pytest.mark.parametrize(
    "vec,expected_msg",
    [
        ([0.0] * 100, "768"),  # wrong dimension — message references prod dim
        ([], "non-empty"),  # empty
        ("not-a-list", "list"),  # wrong type
    ],
)
def test_visual_similarity_400_on_invalid_query_vec(vec, expected_msg, _build_app):
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
def test_visual_similarity_400_on_invalid_top_k(top_k, _build_app):
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
def test_visual_similarity_400_on_invalid_min_similarity(min_sim, _build_app):
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


def test_visual_similarity_404_when_drive_file_missing(_build_app):
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


def test_visual_similarity_404_when_drive_file_soft_deleted(_build_app):
    """Codex F2: soft-deleted DriveFiles must NOT be resolvable via
    these endpoints — racing a delete with an in-flight worker job
    would otherwise let the worker continue processing retired
    content. ``DriveFileRepository.get_by_id`` was extended to
    filter ``is_deleted=False``; the test simulates that contract by
    having the repo return None (same shape as a true 'not found').
    """
    file_id = uuid4()
    app = _build_app(drive_file_obj=None)  # repo returns None for soft-deleted
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


def test_visual_similarity_400_on_invalid_org_id_header(_build_app):
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


def test_visual_similarity_drops_hits_with_missing_scene_id(_build_app):
    """OS doc with no scene_id field is silently skipped — defensive
    against schema drift / partial reads."""
    file_id = uuid4()
    org_id = uuid4()
    drive_file = _drive_file(file_id=file_id, video_id="gd_x", org_id=org_id)

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
                "X-Heimdex-Org-Id": str(org_id),
            },
        )
    assert resp.status_code == 200
    assert [s["scene_id"] for s in resp.json()["scenes"]] == [
        "gd_x_scene_1",
        "gd_x_scene_2",
    ]


def test_visual_similarity_empty_results_returns_200_with_zero_scenes(_build_app):
    file_id = uuid4()
    org_id = uuid4()
    drive_file = _drive_file(file_id=file_id, video_id="gd_a", org_id=org_id)
    scene_client = MagicMock()
    scene_client.search_visual_vector_in_video = AsyncMock(return_value=[])
    app = _build_app(drive_file_obj=drive_file, scene_client_mock=scene_client)

    with TestClient(app) as client:
        resp = client.post(
            f"/internal/videos/{file_id}/scenes-by-visual-similarity",
            json={"query_vec": _vec(), "top_k": 10, "min_similarity": 0.5},
            headers={
                "Authorization": "Bearer test-internal-token",
                "X-Heimdex-Org-Id": str(org_id),
            },
        )
    assert resp.status_code == 200
    assert resp.json()["scenes"] == []


def test_visual_similarity_pattern_b_header_omitted_resolves_org_from_resource(_build_app):
    """Pattern B: ``X-Heimdex-Org-Id`` is OPTIONAL. Workers may omit
    it entirely; the api derives ``org_id`` from the DriveFile's own
    ``org_id`` and forwards it to OpenSearch. This test pins the
    Pattern B contract — bearer + path resource is sufficient."""
    file_id = uuid4()
    org_id = uuid4()
    drive_file = _drive_file(file_id=file_id, video_id="gd_pb", org_id=org_id)

    captured: dict[str, Any] = {}

    async def _capture(**kwargs):
        captured.update(kwargs)
        return []

    scene_client = MagicMock()
    scene_client.search_visual_vector_in_video = _capture
    app = _build_app(drive_file_obj=drive_file, scene_client_mock=scene_client)

    with TestClient(app) as client:
        resp = client.post(
            f"/internal/videos/{file_id}/scenes-by-visual-similarity",
            json={"query_vec": _vec(), "top_k": 10, "min_similarity": 0.0},
            headers={"Authorization": "Bearer test-internal-token"},
        )
    assert resp.status_code == 200
    # API must use the resource's org_id even though the header was omitted.
    assert captured["org_id"] == str(org_id)


def test_visual_similarity_pattern_b_header_mismatch_returns_404_not_403(_build_app):
    """Pattern B cross-validation: caller asserts an org that doesn't
    match the resource's org. Endpoint returns 404 (not 403, not 400)
    so the response is indistinguishable from a true not-found and
    timing doesn't reveal the resource's true tenant."""
    file_id = uuid4()
    resource_org = uuid4()
    asserted_org = uuid4()
    drive_file = _drive_file(file_id=file_id, video_id="gd_pb", org_id=resource_org)
    app = _build_app(drive_file_obj=drive_file)

    with TestClient(app) as client:
        resp = client.post(
            f"/internal/videos/{file_id}/scenes-by-visual-similarity",
            json={"query_vec": _vec(), "top_k": 10, "min_similarity": 0.0},
            headers={
                "Authorization": "Bearer test-internal-token",
                "X-Heimdex-Org-Id": str(asserted_org),
            },
        )
    assert resp.status_code == 404
    # Specifically NOT 403 — 404 is the no-info-leak choice. Pin it
    # so a future "let's be helpful" refactor doesn't regress.
    assert resp.status_code != 403


def test_visual_similarity_requires_bearer_token(_build_app):
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


def test_scenes_content_returns_per_scene_transcript_and_ocr(_build_app):
    file_id = uuid4()
    org_id = uuid4()
    drive_file = _drive_file(file_id=file_id, video_id="gd_xyz", org_id=org_id)

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


def test_scenes_content_drops_scene_belonging_to_other_video(_build_app):
    """Defense in depth: a scene_id from another video on the same
    org must NOT be returned even if the doc_id mget happens to find
    it. Filter by video_id post-mget."""
    file_id = uuid4()
    org_id = uuid4()
    drive_file = _drive_file(file_id=file_id, video_id="gd_correct", org_id=org_id)

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


def test_scenes_content_passes_org_scoped_doc_ids_to_mget(_build_app):
    file_id = uuid4()
    org_id = uuid4()
    drive_file = _drive_file(file_id=file_id, video_id="gd_v", org_id=org_id)

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


def test_scenes_content_skips_missing_scene_ids(_build_app):
    """A scene_id requested but not returned by mget (e.g., deleted
    or cross-org) is simply absent from the response."""
    file_id = uuid4()
    org_id = uuid4()
    drive_file = _drive_file(file_id=file_id, video_id="gd_v", org_id=org_id)

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


def test_scenes_content_400_on_non_list_scene_ids(_build_app):
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


def test_scenes_content_400_on_too_many_scene_ids(_build_app):
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


def test_scenes_content_400_on_non_string_scene_id(_build_app):
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


def test_scenes_content_404_when_drive_file_missing(_build_app):
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


def test_scenes_content_404_when_drive_file_soft_deleted(_build_app):
    """Codex F2: same as the visual-similarity counterpart — workers
    must not be able to read transcripts / OCR for a video the user
    has retired. The repo fix routes both paths through the same
    is_deleted=False filter so this case maps to 404."""
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


def test_scenes_content_empty_scene_ids_returns_empty_list(_build_app):
    file_id = uuid4()
    org_id = uuid4()
    drive_file = _drive_file(file_id=file_id, video_id="gd_v", org_id=org_id)

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


def test_scenes_content_pattern_b_header_omitted_resolves_org_from_resource(_build_app):
    """Pattern B: header optional, org derived from the DriveFile's
    own org_id. Mirror of the visual-similarity counterpart."""
    file_id = uuid4()
    resource_org = uuid4()
    drive_file = _drive_file(file_id=file_id, video_id="gd_pb", org_id=resource_org)

    captured: dict[str, list[str]] = {}

    async def _capture(doc_ids):
        captured["doc_ids"] = doc_ids
        return {}

    scene_client = MagicMock()
    scene_client.mget_scenes = _capture
    app = _build_app(drive_file_obj=drive_file, scene_client_mock=scene_client)

    with TestClient(app) as client:
        resp = client.post(
            f"/internal/videos/{file_id}/scenes-content",
            json={"scene_ids": ["gd_pb_scene_001"]},
            headers={"Authorization": "Bearer test-internal-token"},
        )
    assert resp.status_code == 200
    # doc_ids must be scoped to the RESOURCE's org_id, not anything
    # caller-asserted (since caller didn't assert).
    assert captured["doc_ids"] == [f"{resource_org}:gd_pb_scene_001"]


def test_scenes_content_pattern_b_header_mismatch_returns_404_not_403(_build_app):
    """Pattern B cross-validation on /scenes-content."""
    file_id = uuid4()
    resource_org = uuid4()
    asserted_org = uuid4()
    drive_file = _drive_file(file_id=file_id, video_id="gd_pb", org_id=resource_org)
    app = _build_app(drive_file_obj=drive_file)

    with TestClient(app) as client:
        resp = client.post(
            f"/internal/videos/{file_id}/scenes-content",
            json={"scene_ids": ["gd_pb_scene_001"]},
            headers={
                "Authorization": "Bearer test-internal-token",
                "X-Heimdex-Org-Id": str(asserted_org),
            },
        )
    assert resp.status_code == 404
    assert resp.status_code != 403


def test_scenes_content_requires_bearer_token(_build_app):
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
