"""Tests for the configurable ``dedupe_within_seconds`` parameter on
:meth:`ShortsRenderService.create_render_job`.

The service has a 30s default that's right for HTTP-initiated callers
(anti-double-click). Server-side retry paths — the wizard child runner
and the track-worker — need a wider window because their lease horizon
(default 300s) is well past the default. Without the override, a
crashed-then-relaunched render attempt creates a duplicate render row
+ orphan S3 output.

These tests cover the parameter's contract directly. Real DB-backed
end-to-end coverage exists in the existing
``test_shorts_render_hardening.py`` allowlist test which exercises the
default 30s path.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


def _make_service():
    """Build a ShortsRenderService with mocked deps. Constructed lazily
    so tests can run without docker / opensearch."""
    from app.modules.shorts_render.service import ShortsRenderService

    repo = MagicMock()
    repo.find_recent_duplicate = AsyncMock(return_value=None)
    # ``_to_response`` reads ``job.input_spec.get("scene_clips", [])``
    # — give it a real dict so the auto-MagicMock attribute doesn't
    # leak into Pydantic validation.
    fake_job = MagicMock(
        id=uuid4(),
        status="rendering",
        created_at=datetime.now(timezone.utc),
        completed_at=None,
        render_time_ms=None,
        output_duration_ms=None,
        output_size_bytes=None,
        error=None,
        video_id="gd_test",
        title=None,
        org_id=uuid4(),
        user_id=uuid4(),
        output_s3_key=None,
    )
    fake_job.input_spec = {"scene_clips": []}
    # Refinement chain (migration 056). Default to None so the
    # MagicMock auto-mock doesn't surface as a non-UUID/non-str
    # value through Pydantic validation in _to_response.
    fake_job.replaced_by_render_job_id = None
    fake_job.refined_from_render_job_id = None
    fake_job.refinement_source = None
    fake_job.summary = None
    fake_job.summary_prompt_version = None
    fake_job.summary_generated_at = None
    repo.create = AsyncMock(return_value=fake_job)
    repo.update_status = AsyncMock()
    # service.create_render_job calls ``repository.session.commit()``
    # before publishing to SQS (commit-before-publish race fix). The
    # mock session needs an async commit so the await doesn't crash.
    repo.session = MagicMock()
    repo.session.commit = AsyncMock()
    scene_search = MagicMock()
    service = ShortsRenderService(repository=repo, scene_search=scene_search)
    # Patch internal validate to a no-op so we don't hit OpenSearch.
    service._validate_scene_clips = AsyncMock()
    return service, repo


def _make_payload():
    """Minimal RenderJobCreate satisfying contracts validation."""
    from heimdex_media_contracts.composition.schemas import (
        CompositionSpec, SceneClipSpec,
    )
    from app.modules.shorts_render.schemas import RenderJobCreate

    return RenderJobCreate(
        video_id="gd_test",
        title=None,
        composition=CompositionSpec(scene_clips=[
            SceneClipSpec(
                scene_id="gd_test_scene_001",
                video_id="gd_test",
                source_type="gdrive",
                start_ms=0,
                end_ms=2_000,
                timeline_start_ms=0,
                volume=1.0,
            ),
        ]),
    )


# ---------------------------------------------------------------------
# default behavior (HTTP callers)
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_dedupe_window_is_30_seconds(monkeypatch):
    """When callers omit ``dedupe_within_seconds``, the service uses
    its 30s anti-double-click default. Verify by inspecting the
    ``since`` value passed to the repo's dedupe lookup."""
    # Patch publish_shorts_render_job to a no-op so we don't try to
    # publish to SQS during the test.
    monkeypatch.setattr(
        "app.sqs_producer.publish_shorts_render_job",
        MagicMock(),
    )
    service, repo = _make_service()
    org_id, user_id = uuid4(), uuid4()
    payload = _make_payload()

    before = datetime.now(timezone.utc)
    await service.create_render_job(
        org_id=org_id, user_id=user_id, payload=payload,
    )
    after = datetime.now(timezone.utc)

    repo.find_recent_duplicate.assert_awaited_once()
    since = repo.find_recent_duplicate.await_args.kwargs["since"]
    # ``since`` should be ~30s before "now" — bounded by before/after to
    # tolerate test-runner clock drift.
    assert before - timedelta(seconds=30, milliseconds=100) <= since
    assert since <= after - timedelta(seconds=29, milliseconds=900)


# ---------------------------------------------------------------------
# explicit override (server-side retry callers)
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_explicit_dedupe_window_widens_lookup(monkeypatch):
    """Server-side retry paths (runner, track-worker) pass
    ``dedupe_within_seconds`` past their lease horizon to absorb
    crash-recovery retries. Verify the override propagates to the
    repo lookup."""
    monkeypatch.setattr(
        "app.sqs_producer.publish_shorts_render_job",
        MagicMock(),
    )
    service, repo = _make_service()

    before = datetime.now(timezone.utc)
    await service.create_render_job(
        org_id=uuid4(), user_id=uuid4(), payload=_make_payload(),
        dedupe_within_seconds=360,
    )
    after = datetime.now(timezone.utc)

    since = repo.find_recent_duplicate.await_args.kwargs["since"]
    # 360s window — verify the lookup spans past the 30s default.
    assert before - timedelta(seconds=360, milliseconds=100) <= since
    assert since <= after - timedelta(seconds=359, milliseconds=900)


@pytest.mark.asyncio
async def test_dedupe_window_zero_is_permitted(monkeypatch):
    """Zero is the "now" boundary — any prior row is outside it.
    Effectively disables dedupe (intentional escape hatch for
    callers who want guaranteed-fresh creates). Permitted, not
    rejected."""
    monkeypatch.setattr(
        "app.sqs_producer.publish_shorts_render_job",
        MagicMock(),
    )
    service, repo = _make_service()

    await service.create_render_job(
        org_id=uuid4(), user_id=uuid4(), payload=_make_payload(),
        dedupe_within_seconds=0,
    )

    since = repo.find_recent_duplicate.await_args.kwargs["since"]
    # ``since`` ≈ now — 0s. The repo will find no rows because no row's
    # created_at >= future-of-now (modulo clock skew on the floor).
    now = datetime.now(timezone.utc)
    assert now - timedelta(milliseconds=100) <= since <= now + timedelta(milliseconds=100)


@pytest.mark.asyncio
async def test_dedupe_window_negative_raises_value_error(monkeypatch):
    """Negative windows make no sense — would query rows with
    ``created_at >= now + Xs`` (in the future). Reject loudly so
    a buggy caller sees the error rather than silently never
    deduping."""
    monkeypatch.setattr(
        "app.sqs_producer.publish_shorts_render_job",
        MagicMock(),
    )
    service, _repo = _make_service()

    with pytest.raises(ValueError, match=">= 0"):
        await service.create_render_job(
            org_id=uuid4(), user_id=uuid4(), payload=_make_payload(),
            dedupe_within_seconds=-1,
        )
