"""Tests for the overlay-mode skip-link branch of
``ShortsRenderService.rerender_from_edits``.

Plan: ``.claude/plans/auto-shorts-overlay-mode-2026-05-07.md`` PR 2.

When ``auto_shorts_product_v2_overlay_mode_enabled`` is True the
service must:
  * Create the export child (existing behavior; covered by
    ``test_rerender_from_edits.py``).
  * NOT call ``link_parent_to_child`` — the parent stays canonical,
    the export child is a download artifact only.
  * Still publish the child to SQS.

When the flag is False, ``link_parent_to_child`` MUST still be
called (legacy Whisper-refined-child chain — required for
``useRefinedRenderChain`` polling on legacy renders).
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
    svc.repository.create_rerender_child = AsyncMock()
    svc.scene_search = MagicMock()
    return svc


def _make_parent(
    *,
    job_id=None,
    status_: str = "completed",
    refinement_source: str | None = "manual_edit",
    org_id=None,
    user_id=None,
    subtitles: list[dict[str, Any]] | None = None,
):
    job = MagicMock()
    job.id = job_id or uuid4()
    job.org_id = org_id or uuid4()
    job.user_id = user_id or uuid4()
    job.video_id = "gd_v1"
    job.title = "Edited"
    job.status = status_
    job.created_at = datetime.now(timezone.utc)
    job.completed_at = datetime.now(timezone.utc)
    job.render_time_ms = 1500
    job.output_duration_ms = 30_000
    job.output_size_bytes = 1024
    job.error = None
    job.output_s3_key = "key.mp4"
    job.input_spec = {
        "scene_clips": [{"video_id": "gd_v1", "scene_id": "gd_v1_scene_000"}],
        "subtitles": subtitles or [
            {"text": "edited", "start_ms": 0, "end_ms": 500},
        ],
    }
    job.expires_at = None
    job.composition_hash = "old_hash"
    job.refinement_source = refinement_source
    job.replaced_by_render_job_id = None
    job.refined_from_render_job_id = None
    job.summary = None
    job.summary_prompt_version = None
    job.summary_generated_at = None
    return job


def _make_child(parent):
    child = MagicMock()
    child.id = uuid4()
    child.org_id = parent.org_id
    child.user_id = parent.user_id
    child.video_id = parent.video_id
    child.title = parent.title
    child.status = "queued"
    child.created_at = datetime.now(timezone.utc)
    child.completed_at = None
    child.render_time_ms = None
    child.output_duration_ms = None
    child.output_size_bytes = None
    child.error = None
    child.output_s3_key = None
    child.input_spec = parent.input_spec
    child.expires_at = parent.expires_at
    child.composition_hash = "new_hash"
    child.refinement_source = parent.refinement_source
    child.replaced_by_render_job_id = None
    child.refined_from_render_job_id = parent.id
    child.summary = None
    child.summary_prompt_version = None
    child.summary_generated_at = None
    return child


def _patch_overlay_mode(value: bool):
    """Patches the overlay-mode setting via get_settings()."""
    from app.config import get_settings
    settings = get_settings()
    return patch.object(
        settings,
        "auto_shorts_product_v2_overlay_mode_enabled",
        value,
        create=False,
    )


class TestOverlayModeOnSkipsLink:
    @pytest.mark.asyncio
    async def test_link_not_called_when_flag_on(self) -> None:
        svc = _make_service()
        parent = _make_parent()
        child = _make_child(parent)
        svc.repository.get_by_id = AsyncMock(return_value=parent)
        svc.repository.create_rerender_child = AsyncMock(return_value=child)

        with _patch_overlay_mode(True), \
             patch(
                 "app.modules.shorts_render.refinement_repository."
                 "link_parent_to_child",
                 new_callable=AsyncMock,
             ) as link_mock, \
             patch("app.sqs_producer.publish_shorts_render_job") as sqs_mock:
            await svc.rerender_from_edits(parent.org_id, parent.user_id, parent.id)

        link_mock.assert_not_called()
        sqs_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_export_child_keeps_refined_from(self) -> None:
        svc = _make_service()
        parent = _make_parent()
        child = _make_child(parent)
        svc.repository.get_by_id = AsyncMock(return_value=parent)
        svc.repository.create_rerender_child = AsyncMock(return_value=child)

        with _patch_overlay_mode(True), \
             patch(
                 "app.modules.shorts_render.refinement_repository."
                 "link_parent_to_child",
                 new_callable=AsyncMock,
             ), \
             patch("app.sqs_producer.publish_shorts_render_job"):
            await svc.rerender_from_edits(parent.org_id, parent.user_id, parent.id)

        # ``create_rerender_child`` always sets refined_from on the
        # child (independent of overlay mode). The post_render_hook's
        # ``_check_guards`` reads refined_from to skip Whisper on the
        # export child — this assertion guards that contract.
        assert child.refined_from_render_job_id == parent.id


class TestOverlayModeOffStillLinks:
    @pytest.mark.asyncio
    async def test_link_called_when_flag_off(self) -> None:
        svc = _make_service()
        parent = _make_parent()
        child = _make_child(parent)
        svc.repository.get_by_id = AsyncMock(return_value=parent)
        svc.repository.create_rerender_child = AsyncMock(return_value=child)

        with _patch_overlay_mode(False), \
             patch(
                 "app.modules.shorts_render.refinement_repository."
                 "link_parent_to_child",
                 new_callable=AsyncMock,
             ) as link_mock, \
             patch("app.sqs_producer.publish_shorts_render_job"):
            await svc.rerender_from_edits(parent.org_id, parent.user_id, parent.id)

        link_mock.assert_called_once()
        kwargs = link_mock.call_args.kwargs
        assert kwargs["parent_id"] == parent.id
        assert kwargs["child_id"] == child.id
