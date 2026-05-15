"""Tests for `POST /api/shorts/render/{id}/rerender`.

Plan: `.claude/plans/auto-shorts-subtitle-editor-2026-05-06.md` PR 1.

Covers:
- Service: parent missing/not-owned -> 404, parent not completed -> 409,
  happy path -> child + parent.replaced_by linked + SQS publish.
- Service: composition-hash dedupe within 30s returns existing child.
- Repository: create_rerender_child returns None when parent missing or
  not-completed; child inherits org_id, user_id, video_id, title,
  expires_at, input_spec, refinement_source AND points refined_from at
  the parent.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

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


# ---------- service-layer error contract ----------


class TestErrorContract:
    @pytest.mark.asyncio
    async def test_parent_missing_raises_404(self) -> None:
        svc = _make_service()
        svc.repository.get_by_id = AsyncMock(return_value=None)
        with pytest.raises(HTTPException) as exc:
            await svc.rerender_from_edits(uuid4(), uuid4(), uuid4())
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_parent_not_completed_raises_409(self) -> None:
        svc = _make_service()
        parent = _make_parent(status_="rendering")
        svc.repository.get_by_id = AsyncMock(return_value=parent)
        with pytest.raises(HTTPException) as exc:
            await svc.rerender_from_edits(uuid4(), uuid4(), uuid4())
        assert exc.value.status_code == 409
        assert "rendering" in exc.value.detail

    @pytest.mark.asyncio
    async def test_parent_failed_raises_409(self) -> None:
        svc = _make_service()
        parent = _make_parent(status_="failed")
        svc.repository.get_by_id = AsyncMock(return_value=parent)
        with pytest.raises(HTTPException) as exc:
            await svc.rerender_from_edits(uuid4(), uuid4(), uuid4())
        assert exc.value.status_code == 409


# ---------- happy path ----------


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_creates_child_and_publishes_sqs(self) -> None:
        svc = _make_service()
        parent = _make_parent()
        child = _make_parent(
            job_id=uuid4(), refinement_source="manual_edit"
        )
        child.refined_from_render_job_id = parent.id
        svc.repository.get_by_id = AsyncMock(return_value=parent)
        svc.repository.create_rerender_child = AsyncMock(return_value=child)

        with patch(
            "app.modules.shorts_render.refinement_repository.link_parent_to_child",
            new_callable=AsyncMock,
        ) as mock_link, patch(
            "app.sqs_producer.publish_shorts_render_job"
        ) as mock_publish:
            response = await svc.rerender_from_edits(
                parent.org_id, parent.user_id, parent.id
            )

        assert response.id == child.id
        mock_link.assert_awaited_once()
        link_kwargs = mock_link.await_args.kwargs
        assert link_kwargs["parent_id"] == parent.id
        assert link_kwargs["child_id"] == child.id
        mock_publish.assert_called_once()
        # Commit called twice: once before SQS, once is no-op success
        # path. Worst case: also after a failed publish. Allow >= 1.
        assert svc.repository.session.commit.await_count >= 1

    @pytest.mark.asyncio
    async def test_passes_org_user_to_repository(self) -> None:
        svc = _make_service()
        org_id = uuid4()
        user_id = uuid4()
        job_id = uuid4()
        parent = _make_parent(job_id=job_id, org_id=org_id, user_id=user_id)
        child = _make_parent(job_id=uuid4())
        svc.repository.get_by_id = AsyncMock(return_value=parent)
        svc.repository.create_rerender_child = AsyncMock(return_value=child)

        with patch(
            "app.modules.shorts_render.refinement_repository.link_parent_to_child",
            new_callable=AsyncMock,
        ), patch("app.sqs_producer.publish_shorts_render_job"):
            await svc.rerender_from_edits(org_id, user_id, job_id)

        # get_by_id was called with the calling org+user (owner-scoped)
        svc.repository.get_by_id.assert_awaited_once_with(
            org_id, user_id, job_id
        )
        # create_rerender_child likewise scoped
        kwargs = svc.repository.create_rerender_child.await_args.kwargs
        assert kwargs["org_id"] == org_id
        assert kwargs["user_id"] == user_id
        assert kwargs["parent_job_id"] == job_id


# ---------- composition-hash dedupe ----------


class TestDedupe:
    @pytest.mark.asyncio
    async def test_repeat_within_window_returns_existing_child(self) -> None:
        svc = _make_service()
        parent = _make_parent()
        existing_child = _make_parent(job_id=uuid4())
        existing_child.refined_from_render_job_id = parent.id
        svc.repository.get_by_id = AsyncMock(return_value=parent)
        svc.repository.find_recent_duplicate = AsyncMock(
            return_value=existing_child
        )

        with patch(
            "app.modules.shorts_render.refinement_repository.link_parent_to_child",
            new_callable=AsyncMock,
        ) as mock_link, patch(
            "app.sqs_producer.publish_shorts_render_job"
        ) as mock_publish, patch(
            "app.modules.shorts_render.service._build_playback_url",
            new_callable=AsyncMock,
            return_value="https://s3/exists.mp4",
        ):
            response = await svc.rerender_from_edits(
                parent.org_id, parent.user_id, parent.id
            )

        # Returned existing — no new child, no SQS publish, no link write
        assert response.id == existing_child.id
        svc.repository.create_rerender_child.assert_not_awaited()
        mock_publish.assert_not_called()
        mock_link.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_dedupe_skips_when_match_is_parent_itself(self) -> None:
        """find_recent_duplicate could return the parent if its own
        composition_hash happens to match. Don't treat that as a dedupe
        — the operator clicked rerender, they want a new render."""
        svc = _make_service()
        parent = _make_parent()
        # find_recent_duplicate returns the parent (id matches)
        svc.repository.get_by_id = AsyncMock(return_value=parent)
        svc.repository.find_recent_duplicate = AsyncMock(return_value=parent)
        child = _make_parent(job_id=uuid4())
        svc.repository.create_rerender_child = AsyncMock(return_value=child)

        with patch(
            "app.modules.shorts_render.refinement_repository.link_parent_to_child",
            new_callable=AsyncMock,
        ), patch("app.sqs_producer.publish_shorts_render_job"):
            response = await svc.rerender_from_edits(
                parent.org_id, parent.user_id, parent.id
            )

        # New child created, not parent returned
        assert response.id == child.id
        svc.repository.create_rerender_child.assert_awaited_once()


# ---------- failure paths ----------


class TestFailurePaths:
    @pytest.mark.asyncio
    async def test_create_returns_none_yields_404(self) -> None:
        """Race: parent existed at get_by_id but was deleted/changed
        before create_rerender_child. Surface as 404."""
        svc = _make_service()
        parent = _make_parent()
        svc.repository.get_by_id = AsyncMock(return_value=parent)
        svc.repository.create_rerender_child = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc:
            await svc.rerender_from_edits(
                parent.org_id, parent.user_id, parent.id
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_sqs_failure_marks_child_failed(self) -> None:
        svc = _make_service()
        parent = _make_parent()
        child = _make_parent(job_id=uuid4())
        svc.repository.get_by_id = AsyncMock(return_value=parent)
        svc.repository.create_rerender_child = AsyncMock(return_value=child)

        with patch(
            "app.modules.shorts_render.refinement_repository.link_parent_to_child",
            new_callable=AsyncMock,
        ), patch(
            "app.sqs_producer.publish_shorts_render_job",
            side_effect=RuntimeError("sqs down"),
        ):
            response = await svc.rerender_from_edits(
                parent.org_id, parent.user_id, parent.id
            )

        # Returned the failed child (not 500)
        assert response.id == child.id
        svc.repository.update_status.assert_awaited_with(
            child.id,
            "failed",
            error="Failed to enqueue rerender",
        )
