"""Unit tests for ``src.api_client.ApiClient``.

Exercises every endpoint method against a stubbed ``httpx.Client``
so the HTTP shape (URL, method, headers, body) is pinned. No real
network in the loop.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from src.api_client import ApiClient


def _build_client(*, service_id: str = "") -> tuple[ApiClient, MagicMock]:
    api = ApiClient(
        base_url="https://api.test",
        internal_api_key="test-key",
        service_id=service_id,
    )
    fake_http = MagicMock()
    api._client = fake_http  # noqa: SLF001 — test override
    return api, fake_http


def _ok_response(json_body=None):
    resp = MagicMock()
    resp.json.return_value = json_body or {}
    resp.raise_for_status = MagicMock()
    return resp


# ---------- constructor / headers ----------


def test_constructor_rejects_empty_base_url():
    with pytest.raises(ValueError, match="base_url is required"):
        ApiClient(base_url="", internal_api_key="x")


def test_constructor_rejects_empty_internal_api_key():
    with pytest.raises(ValueError, match="internal_api_key is required"):
        ApiClient(base_url="https://x", internal_api_key="")


def test_service_id_omitted_means_legacy_bearer_only():
    """No ``X-Heimdex-Service-Id`` header when service_id is empty —
    relies on the api's legacy-bearer fallback path."""
    api = ApiClient(base_url="https://x", internal_api_key="t")
    assert "X-Heimdex-Service-Id" not in api._client.headers  # noqa: SLF001


def test_service_id_set_adds_per_service_header():
    api = ApiClient(
        base_url="https://x",
        internal_api_key="t",
        service_id="product-track-worker",
    )
    assert api._client.headers["X-Heimdex-Service-Id"] == "product-track-worker"  # noqa: SLF001


# ---------- claim ----------


def test_claim_posts_correct_url_and_body():
    api, http = _build_client()
    job_id = uuid4()
    http.post.return_value = _ok_response({"ok": True})

    api.claim(
        job_id=job_id,
        claimed_by="worker-x",
        next_stage="tracking",
        lease_seconds=600,
    )
    http.post.assert_called_once()
    args, kwargs = http.post.call_args
    assert args[0] == f"https://api.test/internal/products/{job_id}/claim"
    assert kwargs["json"] == {
        "claimed_by": "worker-x",
        "next_stage": "tracking",
        "lease_seconds": 600,
    }


# ---------- heartbeat ----------


def test_heartbeat_serializes_decimal_cost():
    api, http = _build_client()
    http.post.return_value = _ok_response({})

    api.heartbeat(
        job_id=uuid4(),
        claimed_by="w",
        stage="tracking",
        progress_pct=50,
        progress_label="halfway",
        cost_delta_usd=Decimal("0.123"),
        lease_seconds=600,
    )
    body = http.post.call_args.kwargs["json"]
    assert body["cost_delta_usd"] == "0.123"
    assert body["progress_pct"] == 50
    assert body["progress_label"] == "halfway"


# ---------- complete_track ----------


def test_complete_track_posts_appearances_and_render_id():
    """Body shape pinned: ``catalog_entries`` is always empty for
    track jobs; ``appearances`` is the lib-derived list;
    ``render_job_id`` is None until Phase 3c-B wires real render
    enqueue. The API ``_CompleteRequest`` has ``extra='forbid'``,
    so any extra field would 422."""
    api, http = _build_client()
    job_id = uuid4()
    render_id = uuid4()
    http.post.return_value = _ok_response({})

    api.complete_track(
        job_id=job_id,
        claimed_by="w",
        cost_delta_usd=Decimal("0.50"),
        appearances=[{"scene_id": "s1"}],
        render_job_id=render_id,
    )
    body = http.post.call_args.kwargs["json"]
    assert body["catalog_entries"] == []  # always empty for track
    assert body["appearances"] == [{"scene_id": "s1"}]
    assert body["render_job_id"] == str(render_id)
    # Codex P1 (PR #112 review): the API schema does NOT have a
    # ``stitching_plan`` field. We must not send it.
    assert "stitching_plan" not in body


def test_complete_track_render_job_id_none_when_render_pending():
    """Scaffold path: ``render_job_id`` may be None until Phase 3c-B
    wires the real render enqueue."""
    api, http = _build_client()
    http.post.return_value = _ok_response({})

    api.complete_track(
        job_id=uuid4(),
        claimed_by="w",
        cost_delta_usd=Decimal("0"),
        appearances=[{"scene_id": "s1"}],
        render_job_id=None,
    )
    body = http.post.call_args.kwargs["json"]
    assert body["render_job_id"] is None
    assert "stitching_plan" not in body


# ---------- fail ----------


def test_fail_truncates_long_error_message():
    """Caller (dispatcher) is responsible for truncation, but this
    test pins that we forward the message as-is — caller controls
    the truncation policy. Currently dispatcher caps at 1900 chars."""
    api, http = _build_client()
    http.post.return_value = _ok_response({})

    api.fail(
        job_id=uuid4(),
        claimed_by="w",
        cost_delta_usd=Decimal("0"),
        error_code="internal_error",
        error_message="x" * 2000,
    )
    body = http.post.call_args.kwargs["json"]
    assert len(body["error_message"]) == 2000  # not truncated by client


# ---------- Phase 3b reads ----------


def test_fetch_scenes_with_keyframes_includes_org_header():
    api, http = _build_client()
    file_id = uuid4()
    org_id = uuid4()
    http.get.return_value = _ok_response({"scenes": []})

    api.fetch_scenes_with_keyframes(file_id=file_id, org_id=org_id)
    args, kwargs = http.get.call_args
    assert args[0] == f"https://api.test/internal/videos/{file_id}/scenes-with-keyframes"
    assert kwargs["headers"]["X-Heimdex-Org-Id"] == str(org_id)


def test_find_similar_scenes_extracts_scenes_from_response():
    api, http = _build_client()
    http.post.return_value = _ok_response({
        "video_id": "gd_x",
        "scenes": [
            {"scene_id": "s1", "similarity": 0.9},
            {"scene_id": "s2", "similarity": 0.8},
        ],
    })

    out = api.find_similar_scenes(
        file_id=uuid4(),
        org_id=uuid4(),
        query_vec=[0.1] * 768,
        top_k=10,
        min_similarity=0.5,
    )
    assert len(out) == 2
    assert out[0]["scene_id"] == "s1"


def test_fetch_scenes_content_extracts_scenes_from_response():
    api, http = _build_client()
    http.post.return_value = _ok_response({
        "video_id": "gd_x",
        "scenes": [
            {"scene_id": "s1", "transcript_raw": "hello"},
        ],
    })

    out = api.fetch_scenes_content(
        file_id=uuid4(),
        org_id=uuid4(),
        scene_ids=["s1", "s2"],
    )
    assert len(out) == 1
    assert out[0]["transcript_raw"] == "hello"


# ---------- fetch_catalog_entry (Phase 3c-B) ----------


def test_fetch_catalog_entry_gets_correct_url_and_org_header():
    api, http = _build_client()
    catalog_entry_id = uuid4()
    org_id = uuid4()
    http.get.return_value = _ok_response({
        "catalog_entry_id": str(catalog_entry_id),
        "org_id": str(org_id),
        "video_id": str(uuid4()),
        "canonical_crop_s3_key": "products/X/Y/abc.jpg",
        "canonical_bbox": {"x": 10, "y": 20, "w": 100, "h": 150},
        "llm_label": "핑크 세럼 병",
    })

    out = api.fetch_catalog_entry(
        catalog_entry_id=catalog_entry_id, org_id=org_id,
    )
    args, kwargs = http.get.call_args
    assert args[0] == (
        f"https://api.test/internal/products/catalog/{catalog_entry_id}"
    )
    assert kwargs["headers"]["X-Heimdex-Org-Id"] == str(org_id)
    # Pin the response shape since the worker depends on every key.
    assert out["canonical_crop_s3_key"] == "products/X/Y/abc.jpg"
    assert out["canonical_bbox"] == {"x": 10, "y": 20, "w": 100, "h": 150}
    assert out["llm_label"] == "핑크 세럼 병"
