"""Tests for the ``idempotency_key``-scoped dedupe path (migration 057).

Background: prior to migration 057 the auto-shorts wizard widened
the composition-hash dedupe window to ~360s for crash-retry safety,
but the dedupe scoped only by ``(org_id, user_id, composition_hash)``
— so two DIFFERENT scan_jobs with identical compositions collapsed
into one render row (staging 2026-05-06).

These tests exercise the new semantics:
- ``idempotency_key=None`` matches only rows with NULL key (legacy).
- ``idempotency_key=K`` matches only rows with the SAME ``K`` (or
  the parent that's also keyed K — never NULL-keyed rows).
- The ``service.create_render_job`` ``idempotency_key`` parameter
  forwards to both ``find_recent_duplicate`` and ``create``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.shorts_render.service import ShortsRenderService


def _make_service():
    svc = ShortsRenderService.__new__(ShortsRenderService)
    svc.repository = MagicMock()
    svc.repository.session = MagicMock()
    svc.repository.session.commit = AsyncMock()
    svc.repository.update_status = AsyncMock()
    svc.repository.find_recent_duplicate = AsyncMock(return_value=None)
    svc.repository.create = AsyncMock()
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


def _make_existing_job(*, idempotency_key=None):
    job = MagicMock()
    job.id = uuid4()
    job.status = "queued"
    job.video_id = "vid_123"
    job.title = "Test"
    job.created_at = datetime.now(timezone.utc)
    job.completed_at = None
    job.render_time_ms = None
    job.output_duration_ms = None
    job.output_size_bytes = None
    job.error = None
    job.input_spec = {"scene_clips": [{"video_id": "vid_123", "scene_id": "s1"}]}
    job.composition_hash = "abc"
    job.idempotency_key = idempotency_key
    job.replaced_by_render_job_id = None
    job.refined_from_render_job_id = None
    job.refinement_source = None
    job.summary = None
    job.summary_prompt_version = None
    job.summary_generated_at = None
    return job


# ---- service forwards idempotency_key ----


class TestServiceForwarding:
    @pytest.mark.asyncio
    async def test_create_render_job_forwards_idempotency_key_to_lookup(self) -> None:
        svc = _make_service()
        new_job = _make_existing_job(idempotency_key="scan_job_42")
        svc.repository.create = AsyncMock(return_value=new_job)
        with patch("app.sqs_producer.publish_shorts_render_job"):
            await svc.create_render_job(
                uuid4(), uuid4(), _make_payload(),
                idempotency_key="scan_job_42",
            )
        kwargs = svc.repository.find_recent_duplicate.await_args.kwargs
        assert kwargs["idempotency_key"] == "scan_job_42"

    @pytest.mark.asyncio
    async def test_create_render_job_forwards_idempotency_key_to_create(self) -> None:
        svc = _make_service()
        new_job = _make_existing_job(idempotency_key="scan_job_42")
        svc.repository.create = AsyncMock(return_value=new_job)
        with patch("app.sqs_producer.publish_shorts_render_job"):
            await svc.create_render_job(
                uuid4(), uuid4(), _make_payload(),
                idempotency_key="scan_job_42",
            )
        create_kwargs = svc.repository.create.await_args.kwargs
        assert create_kwargs["idempotency_key"] == "scan_job_42"

    @pytest.mark.asyncio
    async def test_no_idempotency_key_passes_none_through(self) -> None:
        """Direct user-click path (no key) preserves legacy NULL semantics."""
        svc = _make_service()
        new_job = _make_existing_job(idempotency_key=None)
        svc.repository.create = AsyncMock(return_value=new_job)
        with patch("app.sqs_producer.publish_shorts_render_job"):
            await svc.create_render_job(
                uuid4(), uuid4(), _make_payload(),
            )
        lookup_kwargs = svc.repository.find_recent_duplicate.await_args.kwargs
        assert lookup_kwargs["idempotency_key"] is None
        create_kwargs = svc.repository.create.await_args.kwargs
        assert create_kwargs["idempotency_key"] is None


# ---- dedupe semantics ----


class TestDedupeSemantics:
    @pytest.mark.asyncio
    async def test_same_key_returns_existing(self) -> None:
        """Same key + same hash within window → dedupe → return existing."""
        svc = _make_service()
        existing = _make_existing_job(idempotency_key="scan_job_X")
        svc.repository.find_recent_duplicate = AsyncMock(return_value=existing)

        with patch("app.sqs_producer.publish_shorts_render_job") as mock_pub:
            response = await svc.create_render_job(
                uuid4(), uuid4(), _make_payload(),
                idempotency_key="scan_job_X",
            )

        assert response.id == existing.id
        # Did NOT create a new row, did NOT publish to SQS
        svc.repository.create.assert_not_called()
        mock_pub.assert_not_called()

    @pytest.mark.asyncio
    async def test_different_key_does_not_dedupe(self) -> None:
        """Different key (even with same hash) → NOT a dedupe → create fresh row.

        This is the staging 2026-05-06 bug fix: two scan_jobs producing
        identical compositions stay distinct.
        """
        svc = _make_service()
        # find_recent_duplicate returns None when scoped to the new key
        svc.repository.find_recent_duplicate = AsyncMock(return_value=None)
        new_job = _make_existing_job(idempotency_key="scan_job_DIFFERENT")
        svc.repository.create = AsyncMock(return_value=new_job)

        with patch("app.sqs_producer.publish_shorts_render_job") as mock_pub:
            response = await svc.create_render_job(
                uuid4(), uuid4(), _make_payload(),
                idempotency_key="scan_job_DIFFERENT",
            )

        # New row created
        assert response.id == new_job.id
        svc.repository.create.assert_called_once()
        # Confirm the lookup was scoped by the new key
        lookup_kwargs = svc.repository.find_recent_duplicate.await_args.kwargs
        assert lookup_kwargs["idempotency_key"] == "scan_job_DIFFERENT"
        # SQS published
        mock_pub.assert_called_once()

    @pytest.mark.asyncio
    async def test_null_key_only_matches_null_rows(self) -> None:
        """idempotency_key=None must scope find_recent_duplicate to NULL rows."""
        svc = _make_service()
        # The repo's IS NULL clause is exercised at the repository
        # layer (DB-level); from the service we just confirm the
        # kwarg is passed.
        svc.repository.find_recent_duplicate = AsyncMock(return_value=None)
        new_job = _make_existing_job(idempotency_key=None)
        svc.repository.create = AsyncMock(return_value=new_job)
        with patch("app.sqs_producer.publish_shorts_render_job"):
            await svc.create_render_job(uuid4(), uuid4(), _make_payload())
        assert (
            svc.repository.find_recent_duplicate.await_args.kwargs["idempotency_key"]
            is None
        )
