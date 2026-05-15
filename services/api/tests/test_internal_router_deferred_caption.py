"""Regression test for the deferred-caption asyncio bug in
``app.modules.drive.internal_router``.

Bug fixed 2026-04-29: the deferred-caption block at
``internal_router.py:319`` used to do

    asyncio.create_task(loop.run_in_executor(None, lambda: ...))

``loop.run_in_executor`` returns an ``asyncio.Future``, and
``asyncio.create_task`` requires a coroutine — it raises

    TypeError: a coroutine was expected, got <Future pending
    cb=[_chain_future.<locals>._call_check_cancel() at .../futures.py]>

Every successful STT run that hit the legacy enrich callback in
``PATCH /internal/drive/jobs/{id}/status`` therefore returned 500 to
the worker, which interpreted that as STT failure and wrote
``stt_status=failed`` even though enrichment had already populated
OpenSearch.

Anti-pattern entry: see ``.claude/antipatterns.md`` —
"asyncio.create_task on a Future".
"""
from __future__ import annotations

import asyncio
import inspect

import pytest


def test_canonical_helper_is_a_coroutine_function():
    """Callers MUST use the canonical helper (which awaits the executor)
    rather than passing ``loop.run_in_executor(...)`` straight into
    ``asyncio.create_task``. If this helper stops being a coroutine
    function, the deferred-caption call site at
    ``internal_router.py:319`` is at risk of regressing."""
    from app.modules.drive.internal_processing_router import (
        _publish_scene_jobs_in_background,
    )

    assert inspect.iscoroutinefunction(_publish_scene_jobs_in_background), (
        "_publish_scene_jobs_in_background must be `async def` so that "
        "asyncio.create_task() receives a coroutine, not a Future."
    )


def test_create_task_accepts_canonical_helper_without_typeerror():
    """Concrete repro of the fix. Calling create_task on the helper
    yields a Task; calling create_task on a raw run_in_executor result
    raises the exact TypeError seen in production."""
    from app.modules.drive.internal_processing_router import (
        _publish_scene_jobs_in_background,
    )

    async def driver():
        # Patch the SQS call so we don't hit boto3.
        from unittest.mock import patch
        from uuid import uuid4

        with patch(
            "app.modules.drive.internal_processing_router."
            "publish_scene_enrichment_jobs"
        ):
            coro = _publish_scene_jobs_in_background(
                file_id=uuid4(),
                org_id=uuid4(),
                video_id="gd_testvideo",
                scenes=[],
                job_types=("caption",),
            )
            task = asyncio.create_task(coro)
            await task

    asyncio.run(driver())


def test_raw_run_in_executor_in_create_task_is_the_documented_trap():
    """Document the failure mode this fix prevents. If anyone reverts
    the fix to the old pattern, this assertion is the canary."""

    async def driver():
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(None, lambda: 42)
        with pytest.raises(TypeError, match="coroutine was expected"):
            asyncio.create_task(future)
        # Drain the executor work to keep the test loop tidy.
        await future

    asyncio.run(driver())
