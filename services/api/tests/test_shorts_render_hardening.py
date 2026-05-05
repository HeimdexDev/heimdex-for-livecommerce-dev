# pyright: reportUnknownParameterType=false, reportMissingParameterType=false, reportAny=false, reportUnusedCallResult=false, reportUnknownVariableType=false, reportUnknownMemberType=false
"""Tests for the shorts-render hardening pass (Item 2).

Covers three independent concerns:
1. Idempotency via composition hash + recent-dupe window
2. Per-user sliding-window rate limit (10/hr)
3. Tightened user scoping on get_render_job / get_render_job_record / delete

Mocks the repo + S3 client; no DB, no boto3, no SQS.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.shorts_render.rate_limit import (
    _MAX_REQUESTS,
    _WINDOW_SECONDS,
    check_shorts_render_rate_limit,
    reset as reset_rate_limit,
)
from app.modules.shorts_render.service import (
    ShortsRenderService,
    compute_composition_hash,
)


# ---------------------------------------------------------------------------
# Composition hash
# ---------------------------------------------------------------------------


class TestComputeCompositionHash:
    def test_hash_is_64_hex_chars(self):
        h = compute_composition_hash({"a": 1, "b": [1, 2, 3]})
        assert len(h) == 64
        int(h, 16)  # parses as hex, raises if not

    def test_hash_is_deterministic(self):
        body = {"clips": [{"id": "a", "start_ms": 0, "end_ms": 1000}]}
        assert compute_composition_hash(body) == compute_composition_hash(body)

    def test_hash_ignores_dict_key_ordering(self):
        """sort_keys=True must make `{a:1, b:2}` hash the same as `{b:2, a:1}`."""
        h1 = compute_composition_hash({"a": 1, "b": 2})
        h2 = compute_composition_hash({"b": 2, "a": 1})
        assert h1 == h2

    def test_different_content_different_hash(self):
        h1 = compute_composition_hash({"a": 1})
        h2 = compute_composition_hash({"a": 2})
        assert h1 != h2

    def test_accepts_pydantic_model_via_model_dump(self):
        fake_model = MagicMock()
        fake_model.model_dump.return_value = {"a": 1}
        h = compute_composition_hash(fake_model)
        fake_model.model_dump.assert_called_once()
        assert h == compute_composition_hash({"a": 1})


# ---------------------------------------------------------------------------
# Idempotency — create_render_job dedupe path
# ---------------------------------------------------------------------------


def _make_service_with_mocks():
    """Build a ShortsRenderService stub wired to mock repo + scene_search."""
    svc = ShortsRenderService.__new__(ShortsRenderService)
    svc.repository = MagicMock()
    svc.repository.find_recent_duplicate = AsyncMock(return_value=None)
    svc.repository.create = AsyncMock()
    svc.repository.update_status = AsyncMock()
    # service.create_render_job calls ``repository.session.commit()``
    # before publishing (commit-before-publish race fix).
    svc.repository.session = MagicMock()
    svc.repository.session.commit = AsyncMock()
    svc.scene_search = MagicMock()
    svc._validate_scene_clips = AsyncMock()
    return svc


def _make_payload(video_id: str = "vid_123"):
    payload = MagicMock()
    payload.video_id = video_id
    payload.title = "Test"
    payload.composition = MagicMock()
    payload.composition.model_dump.return_value = {
        "output": {"width": 406, "height": 720, "fps": 30},
        "scene_clips": [{"scene_id": "s1", "start_ms": 0, "end_ms": 1000}],
        "subtitles": [],
    }
    payload.composition.scene_clips = [MagicMock()]
    payload.composition.subtitles = []
    return payload


def _make_existing_job(composition_hash: str, age_seconds: int = 5):
    job = MagicMock()
    job.id = uuid4()
    job.status = "queued"
    job.video_id = "vid_123"
    job.title = "Test"
    job.composition_hash = composition_hash
    job.input_spec = {"scene_clips": [{"video_id": "vid_123", "scene_id": "s1"}]}
    job.created_at = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    job.completed_at = None
    job.render_time_ms = None
    job.output_duration_ms = None
    job.output_size_bytes = None
    job.error = None
    return job


@pytest.mark.asyncio
async def test_duplicate_within_window_returns_existing_job_without_creating_new():
    svc = _make_service_with_mocks()
    payload = _make_payload()
    hash_value = compute_composition_hash(payload.composition.model_dump())
    existing = _make_existing_job(hash_value, age_seconds=5)
    svc.repository.find_recent_duplicate = AsyncMock(return_value=existing)

    with patch("app.sqs_producer.publish_shorts_render_job"):
        response = await svc.create_render_job(uuid4(), uuid4(), payload)

    # Returned the existing job, did NOT create a new one, did NOT enqueue SQS
    assert response.id == existing.id
    svc.repository.create.assert_not_called()


@pytest.mark.asyncio
async def test_no_duplicate_match_creates_new_job():
    svc = _make_service_with_mocks()
    payload = _make_payload()
    svc.repository.find_recent_duplicate = AsyncMock(return_value=None)
    new_job = _make_existing_job("abc", age_seconds=0)
    svc.repository.create = AsyncMock(return_value=new_job)

    with patch("app.sqs_producer.publish_shorts_render_job"):
        await svc.create_render_job(uuid4(), uuid4(), payload)

    svc.repository.create.assert_called_once()
    # composition_hash was passed to create
    create_kwargs = svc.repository.create.call_args.kwargs
    assert "composition_hash" in create_kwargs
    assert len(create_kwargs["composition_hash"]) == 64


@pytest.mark.asyncio
async def test_find_recent_duplicate_called_with_correct_window():
    """The dedupe query's ``since`` must be roughly now - 30s, not wider."""
    svc = _make_service_with_mocks()
    payload = _make_payload()
    new_job = _make_existing_job("abc")
    svc.repository.create = AsyncMock(return_value=new_job)

    before = datetime.now(timezone.utc)
    with patch("app.sqs_producer.publish_shorts_render_job"):
        await svc.create_render_job(uuid4(), uuid4(), payload)
    after = datetime.now(timezone.utc)

    svc.repository.find_recent_duplicate.assert_awaited_once()
    kwargs = svc.repository.find_recent_duplicate.call_args.kwargs
    since = kwargs["since"]
    # 30 second window ± test execution slack
    assert before - timedelta(seconds=31) <= since <= after - timedelta(seconds=29)


@pytest.mark.asyncio
async def test_dedupe_is_scoped_to_user_and_org():
    """The dedupe query must pass org_id + user_id, not just one."""
    svc = _make_service_with_mocks()
    payload = _make_payload()
    new_job = _make_existing_job("abc")
    svc.repository.create = AsyncMock(return_value=new_job)

    org_id = uuid4()
    user_id = uuid4()
    with patch("app.sqs_producer.publish_shorts_render_job"):
        await svc.create_render_job(org_id, user_id, payload)

    kwargs = svc.repository.find_recent_duplicate.call_args.kwargs
    assert kwargs["org_id"] == org_id
    assert kwargs["user_id"] == user_id


# ---------------------------------------------------------------------------
# Rate limit — check_shorts_render_rate_limit
# ---------------------------------------------------------------------------


class TestRateLimit:
    def setup_method(self):
        reset_rate_limit()

    def teardown_method(self):
        reset_rate_limit()

    def test_allows_under_cap(self):
        org_id = uuid4()
        user_id = uuid4()
        # 10 requests should all pass
        for _ in range(_MAX_REQUESTS):
            check_shorts_render_rate_limit(org_id, user_id)

    def test_blocks_at_cap(self):
        org_id = uuid4()
        user_id = uuid4()
        for _ in range(_MAX_REQUESTS):
            check_shorts_render_rate_limit(org_id, user_id)
        with pytest.raises(HTTPException) as exc:
            check_shorts_render_rate_limit(org_id, user_id)
        assert exc.value.status_code == 429
        assert "rate limit" in exc.value.detail.lower()

    def test_isolation_per_user(self):
        """Two users in the same org do NOT share a bucket."""
        org_id = uuid4()
        user_a = uuid4()
        user_b = uuid4()

        # User A exhausts their bucket
        for _ in range(_MAX_REQUESTS):
            check_shorts_render_rate_limit(org_id, user_a)
        with pytest.raises(HTTPException):
            check_shorts_render_rate_limit(org_id, user_a)

        # User B is still clean
        check_shorts_render_rate_limit(org_id, user_b)

    def test_isolation_per_org(self):
        """Same user in two different orgs has independent buckets."""
        user_id = uuid4()
        org_a = uuid4()
        org_b = uuid4()

        for _ in range(_MAX_REQUESTS):
            check_shorts_render_rate_limit(org_a, user_id)

        # org_b still accepts
        check_shorts_render_rate_limit(org_b, user_id)

    def test_window_rolls_after_expiry(self):
        """Entries older than _WINDOW_SECONDS are dropped."""
        import time
        import app.modules.shorts_render.rate_limit as rl

        org_id = uuid4()
        user_id = uuid4()
        key = f"{org_id}:{user_id}"

        # Plant _MAX_REQUESTS entries 2× the window in the past.
        # Must compute relative to time.monotonic() — on a fresh process
        # (e.g. CI) monotonic() returns a small number, so a literal 0.0
        # is NOT older than now - window and won't get cleaned.
        stale_time = time.monotonic() - (_WINDOW_SECONDS * 2)
        with rl._lock:
            rl._buckets[key] = [stale_time] * _MAX_REQUESTS

        # Next request should succeed — the stale entries get cleaned
        check_shorts_render_rate_limit(org_id, user_id)


# ---------------------------------------------------------------------------
# User scoping — get_render_job / get_render_job_record / delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_render_job_passes_user_id_to_repository():
    svc = _make_service_with_mocks()
    svc.repository.get_by_id = AsyncMock(return_value=None)

    org_id = uuid4()
    user_id = uuid4()
    job_id = uuid4()

    with pytest.raises(HTTPException) as exc:
        await svc.get_render_job(org_id, user_id, job_id)

    assert exc.value.status_code == 404
    svc.repository.get_by_id.assert_awaited_once_with(org_id, user_id, job_id)


@pytest.mark.asyncio
async def test_get_render_job_record_passes_user_id_to_repository():
    svc = _make_service_with_mocks()
    svc.repository.get_by_id = AsyncMock(return_value=None)

    org_id = uuid4()
    user_id = uuid4()
    job_id = uuid4()

    result = await svc.get_render_job_record(org_id, user_id, job_id)
    assert result is None
    svc.repository.get_by_id.assert_awaited_once_with(org_id, user_id, job_id)


@pytest.mark.asyncio
async def test_delete_render_job_passes_user_id_to_repository():
    svc = _make_service_with_mocks()
    job = _make_existing_job("abc")
    job.output_s3_key = None  # skip S3 path
    svc.repository.get_by_id = AsyncMock(return_value=job)
    svc.repository.delete = AsyncMock(return_value=True)

    org_id = uuid4()
    user_id = uuid4()
    job_id = uuid4()

    await svc.delete_render_job(org_id, user_id, job_id)

    svc.repository.get_by_id.assert_awaited_once_with(org_id, user_id, job_id)
    svc.repository.delete.assert_awaited_once_with(org_id, user_id, job_id)


# ---------------------------------------------------------------------------
# Phase 3: title editing
# ---------------------------------------------------------------------------


def _make_completed_job(title: str = "Original", *, with_output: bool = False):
    """Job stub for title-update tests. ``with_output`` toggles the S3
    key so the service-layer download_url branch can be exercised.

    ``input_spec`` MUST be a real dict (not a MagicMock attribute) so
    ``_to_response`` can ``.get("scene_clips")`` on it without
    Pydantic balking on the resulting MagicMock-typed thumbnail
    fields.
    """
    job = MagicMock()
    job.id = uuid4()
    job.video_id = "vid_123"
    job.title = title
    job.status = "completed" if with_output else "queued"
    job.created_at = datetime.now(timezone.utc)
    job.completed_at = datetime.now(timezone.utc) if with_output else None
    job.render_time_ms = 1500 if with_output else None
    job.output_duration_ms = 30_000 if with_output else None
    job.output_size_bytes = 1024 * 1024 if with_output else None
    job.error = None
    job.output_s3_key = "output.mp4" if with_output else None
    job.input_spec = {
        "scene_clips": [{"video_id": "vid_123", "scene_id": "vid_123_scene_000"}],
    }
    return job


@pytest.mark.asyncio
async def test_update_render_job_title_passes_org_user_to_repository():
    """Owner-scoped: org_id + user_id must reach the repo update_title call.

    Guards against accidental cross-tenant rename if the route ever
    drops the user_id arg the way the GET path used to.
    """
    svc = _make_service_with_mocks()
    updated = _make_completed_job("New title")
    svc.repository.update_title = AsyncMock(return_value=updated)

    org_id = uuid4()
    user_id = uuid4()
    job_id = uuid4()

    result = await svc.update_render_job_title(org_id, user_id, job_id, "New title")

    svc.repository.update_title.assert_awaited_once_with(
        org_id, user_id, job_id, "New title",
    )
    assert result.title == "New title"


@pytest.mark.asyncio
async def test_update_render_job_title_404_when_repo_returns_none():
    """update_title returns None on missing-or-not-owned. Service must
    surface that as 404 (matching get_render_job semantics so the FE
    doesn't have to special-case "not yours" vs "doesn't exist").
    """
    svc = _make_service_with_mocks()
    svc.repository.update_title = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc:
        await svc.update_render_job_title(uuid4(), uuid4(), uuid4(), "x")

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_render_job_title_clears_when_set_to_none():
    """``None`` is a valid title (clears it). Service forwards as-is."""
    svc = _make_service_with_mocks()
    cleared = _make_completed_job(title=None)
    svc.repository.update_title = AsyncMock(return_value=cleared)

    org_id = uuid4()
    user_id = uuid4()
    job_id = uuid4()

    result = await svc.update_render_job_title(org_id, user_id, job_id, None)

    svc.repository.update_title.assert_awaited_once_with(
        org_id, user_id, job_id, None,
    )
    assert result.title is None


@pytest.mark.asyncio
async def test_update_render_job_title_completed_job_includes_download_url():
    """Response shape parity with get_render_job: completed jobs get a
    download_url so the FE can immediately offer download after rename.

    Post 2026-05-06 fix: download_url is a PRESIGNED S3 URL the
    browser can use directly (``<video src>`` / anchor click). It is
    NOT the api's ``/api/shorts/render/{id}/download`` endpoint —
    that path required Bearer auth and 401'd silently in browsers.
    """
    svc = _make_service_with_mocks()
    job = _make_completed_job("renamed", with_output=True)
    svc.repository.update_title = AsyncMock(return_value=job)

    result = await svc.update_render_job_title(uuid4(), uuid4(), job.id, "renamed")

    assert result.download_url is not None
    # Must be an absolute URL with the S3 signing query params, not
    # the api-relative path.
    assert result.download_url.startswith("http")
    assert "X-Amz-Signature=" in result.download_url


@pytest.mark.asyncio
async def test_update_render_job_title_in_flight_job_no_download_url():
    """In-flight (queued/rendering) jobs have no S3 output yet.
    download_url stays None so the FE doesn't try to fetch a 404.
    """
    svc = _make_service_with_mocks()
    job = _make_completed_job("renamed", with_output=False)  # status=queued
    svc.repository.update_title = AsyncMock(return_value=job)

    result = await svc.update_render_job_title(uuid4(), uuid4(), job.id, "renamed")

    assert result.download_url is None


def test_render_job_title_update_schema_rejects_oversized_title():
    """``max_length=255`` matches the DB column. Pydantic raises on
    overflow; FastAPI surfaces it as 422.
    """
    from app.modules.shorts_render.schemas import RenderJobTitleUpdate
    from pydantic import ValidationError

    too_long = "a" * 256
    with pytest.raises(ValidationError):
        RenderJobTitleUpdate(title=too_long)


def test_render_job_title_update_schema_accepts_empty_and_none():
    """Both empty string and None are valid title-clear payloads."""
    from app.modules.shorts_render.schemas import RenderJobTitleUpdate

    assert RenderJobTitleUpdate(title=None).title is None
    assert RenderJobTitleUpdate(title="").title == ""
    assert RenderJobTitleUpdate().title is None  # default
