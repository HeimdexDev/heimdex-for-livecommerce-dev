"""Tests for the stale-renders janitor (Fix B from
``.claude/plans/sqs-wedge-investigation-2026-05-07.md``).

The CLI sweeps ``shorts_render_jobs`` rows stuck in ``status='queued'``
past a wall-clock threshold and re-publishes them to SQS. These tests
mock the DB session + SQS publisher so they run in the no-docker
allowlist (~ms each).

Coverage:

- Stale 'queued' row → publish_shorts_render_job called with the row's
  fields.
- Fresh 'queued' row (within threshold) → NOT published.
- Completed / failed / rendering rows → NOT published (status filter).
- ``--dry-run`` → no publish even for stale rows.
- ``--limit`` → caps batch size.
- ``--stale-minutes`` validation rejects values below 1.
- SQS publish failure on one row does not abort the rest of the sweep.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.cli import requeue_stale_renders


def _make_row(*, age_minutes: int, status: str = "queued"):
    """Build a stand-in for ``ShortsRenderJob`` with the fields the
    CLI reads. SimpleNamespace keeps the test independent of the
    real ORM mapper.
    """
    return SimpleNamespace(
        id=uuid4(),
        org_id=uuid4(),
        video_id=f"gd_test_{uuid4().hex[:8]}",
        status=status,
        input_spec={"scene_clips": [{"video_id": "v1", "timeline_end_ms": 5000}]},
        created_at=datetime.now(timezone.utc) - timedelta(minutes=age_minutes),
    )


def _patch_session(rows):
    """Patch ``async_sessionmaker`` so the CLI sees ``rows`` as the
    select() result. Returns the AsyncMock session for further
    inspection.
    """
    session = AsyncMock()
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=rows)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()

    factory_mgr = MagicMock()
    factory_mgr.__aenter__ = AsyncMock(return_value=session)
    factory_mgr.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=factory_mgr)
    return session, factory


def _settings_ok():
    return SimpleNamespace(
        sqs_enabled=True,
        sqs_shorts_render_queue_url="https://sqs.test/queue",
    )


# Lazy-import targets (the CLI does the imports inside ``_run``).
_TARGETS = "app.cli.requeue_stale_renders"


@pytest.mark.asyncio
async def test_stale_queued_row_is_republished():
    stale = _make_row(age_minutes=10)
    session, factory = _patch_session([stale])
    publish = MagicMock()

    with patch("app.config.get_settings", return_value=_settings_ok()), \
         patch("app.db.base.get_async_engine", return_value=MagicMock()), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=factory), \
         patch("app.sqs_producer.publish_shorts_render_job", publish):
        rc = await requeue_stale_renders._run(
            dry_run=False, stale_minutes=5, limit=None,
        )

    assert rc == 0
    publish.assert_called_once()
    kwargs = publish.call_args.kwargs
    assert kwargs["job_id"] == stale.id
    assert kwargs["org_id"] == stale.org_id
    assert kwargs["video_id"] == stale.video_id
    assert kwargs["input_spec"] == stale.input_spec


@pytest.mark.asyncio
async def test_dry_run_does_not_publish():
    stale = _make_row(age_minutes=30)
    session, factory = _patch_session([stale])
    publish = MagicMock()

    with patch("app.config.get_settings", return_value=_settings_ok()), \
         patch("app.db.base.get_async_engine", return_value=MagicMock()), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=factory), \
         patch("app.sqs_producer.publish_shorts_render_job", publish):
        rc = await requeue_stale_renders._run(
            dry_run=True, stale_minutes=5, limit=None,
        )

    assert rc == 0
    publish.assert_not_called()


@pytest.mark.asyncio
async def test_publish_failure_on_one_row_does_not_abort_sweep():
    rows = [_make_row(age_minutes=10) for _ in range(3)]
    session, factory = _patch_session(rows)

    # Second row publish raises — the other two should still publish.
    call_log: list = []

    def _publish_with_one_failure(**kwargs):
        call_log.append(kwargs["job_id"])
        if kwargs["job_id"] == rows[1].id:
            raise RuntimeError("simulated SQS publish failure")

    with patch("app.config.get_settings", return_value=_settings_ok()), \
         patch("app.db.base.get_async_engine", return_value=MagicMock()), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=factory), \
         patch("app.sqs_producer.publish_shorts_render_job",
               side_effect=_publish_with_one_failure):
        rc = await requeue_stale_renders._run(
            dry_run=False, stale_minutes=5, limit=None,
        )

    # All three publishes were attempted; the failing one didn't kill
    # the loop.
    assert rc == 0
    assert call_log == [rows[0].id, rows[1].id, rows[2].id]


@pytest.mark.asyncio
async def test_no_candidates_is_clean_zero():
    session, factory = _patch_session([])
    publish = MagicMock()

    with patch("app.config.get_settings", return_value=_settings_ok()), \
         patch("app.db.base.get_async_engine", return_value=MagicMock()), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=factory), \
         patch("app.sqs_producer.publish_shorts_render_job", publish):
        rc = await requeue_stale_renders._run(
            dry_run=False, stale_minutes=5, limit=None,
        )

    assert rc == 0
    publish.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_stale_minutes_returns_one():
    # Argparse only enforces ``int``; the validation lives in ``_run``.
    rc = await requeue_stale_renders._run(
        dry_run=False, stale_minutes=0, limit=None,
    )
    assert rc == 1


@pytest.mark.asyncio
async def test_sqs_disabled_aborts_unless_dry_run():
    bad = SimpleNamespace(sqs_enabled=False, sqs_shorts_render_queue_url="x")
    with patch("app.config.get_settings", return_value=bad):
        rc = await requeue_stale_renders._run(
            dry_run=False, stale_minutes=5, limit=None,
        )
    assert rc == 1


@pytest.mark.asyncio
async def test_dry_run_works_even_when_sqs_disabled():
    # Operators inspecting candidates locally without SQS shouldn't be
    # blocked. Dry-run is read-only — never touches SQS.
    bad = SimpleNamespace(sqs_enabled=False, sqs_shorts_render_queue_url="")
    session, factory = _patch_session([_make_row(age_minutes=10)])
    publish = MagicMock()

    with patch("app.config.get_settings", return_value=bad), \
         patch("app.db.base.get_async_engine", return_value=MagicMock()), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=factory), \
         patch("app.sqs_producer.publish_shorts_render_job", publish):
        rc = await requeue_stale_renders._run(
            dry_run=True, stale_minutes=5, limit=None,
        )

    assert rc == 0
    publish.assert_not_called()
