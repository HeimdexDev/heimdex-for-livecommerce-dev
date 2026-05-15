"""Tests for ``PATCH /api/shorts/render/{job_id}/subtitles``.

PR 5 of the auto-shorts whisper-subtitles plan. Covers:

- Service forwards the manual-edit subtitles to the repo with org+user scope.
- 404 when the repo returns ``None`` (missing or not-owned).
- Repository builds a fresh ``input_spec`` dict (assigning a NEW dict
  is the only way SQLAlchemy detects a JSONB change).
- Repository sets ``refinement_source='manual_edit'`` atomically.
- Schema accepts an empty list (operator deleted everything).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from heimdex_media_contracts.composition import SubtitleSpec

from app.modules.shorts_render.schemas import RenderJobSubtitlesUpdate
from app.modules.shorts_render.service import ShortsRenderService


def _make_service_with_mocks() -> ShortsRenderService:
    repo = MagicMock()
    svc = ShortsRenderService(repository=repo, scene_search=MagicMock())
    return svc


def _make_job(
    *,
    job_id=None,
    refinement_source: str | None = None,
    subtitles: list[dict[str, Any]] | None = None,
):
    job = MagicMock()
    job.id = job_id or uuid4()
    job.video_id = "gd_v1"
    job.title = "T"
    job.status = "completed"
    job.created_at = datetime.now(timezone.utc)
    job.completed_at = datetime.now(timezone.utc)
    job.render_time_ms = 1500
    job.output_duration_ms = 30_000
    job.output_size_bytes = 1024
    job.error = None
    job.output_s3_key = "key.mp4"
    job.input_spec = {
        "scene_clips": [{"video_id": "gd_v1", "scene_id": "gd_v1_scene_000"}],
        "subtitles": subtitles or [],
    }
    job.refinement_source = refinement_source
    job.replaced_by_render_job_id = None
    job.refined_from_render_job_id = None
    # Migration 059 — explicit None so _to_response gets real values
    # rather than auto-created MagicMock attributes.
    job.summary = None
    job.summary_prompt_version = None
    job.summary_generated_at = None
    return job


# ---- Schema tests ----


class TestSchema:
    def test_accepts_well_formed_subtitle_list(self) -> None:
        body = RenderJobSubtitlesUpdate(
            subtitles=[
                SubtitleSpec(text="안녕", start_ms=0, end_ms=500),
                SubtitleSpec(text="하세요", start_ms=600, end_ms=1100),
            ]
        )
        assert len(body.subtitles) == 2
        assert body.subtitles[0].text == "안녕"

    def test_empty_list_is_valid(self) -> None:
        # Operator deleted every subtitle; manual_edit flag still applies.
        body = RenderJobSubtitlesUpdate(subtitles=[])
        assert body.subtitles == []

    def test_default_is_empty_list(self) -> None:
        body = RenderJobSubtitlesUpdate()
        assert body.subtitles == []


# ---- Service-layer tests (org+user scoping, 404, atomicity) ----


class TestService:
    @pytest.mark.asyncio
    async def test_passes_org_user_to_repository(self) -> None:
        svc = _make_service_with_mocks()
        updated = _make_job(refinement_source="manual_edit")
        svc.repository.update_subtitles_with_manual_edit = AsyncMock(
            return_value=updated
        )

        org_id = uuid4()
        user_id = uuid4()
        job_id = uuid4()
        new_subs = [
            SubtitleSpec(text="hi", start_ms=0, end_ms=400),
        ]

        await svc.update_render_job_subtitles(org_id, user_id, job_id, new_subs)

        svc.repository.update_subtitles_with_manual_edit.assert_awaited_once()
        args, kwargs = svc.repository.update_subtitles_with_manual_edit.call_args
        # First three positional args: org_id, user_id, job_id
        assert args[0] == org_id
        assert args[1] == user_id
        assert args[2] == job_id
        # Subtitles arg: list of plain dicts (NOT SubtitleSpec objects;
        # the repository stays free of contract-package imports).
        sent = args[3]
        assert isinstance(sent, list)
        assert isinstance(sent[0], dict)
        assert sent[0]["text"] == "hi"

    @pytest.mark.asyncio
    async def test_404_when_repo_returns_none(self) -> None:
        svc = _make_service_with_mocks()
        svc.repository.update_subtitles_with_manual_edit = AsyncMock(
            return_value=None
        )

        with pytest.raises(HTTPException) as exc:
            await svc.update_render_job_subtitles(
                uuid4(), uuid4(), uuid4(), [SubtitleSpec(text="x", start_ms=0, end_ms=100)],
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_response_includes_manual_edit_flag(self) -> None:
        svc = _make_service_with_mocks()
        updated = _make_job(refinement_source="manual_edit")
        svc.repository.update_subtitles_with_manual_edit = AsyncMock(
            return_value=updated
        )

        result = await svc.update_render_job_subtitles(
            uuid4(),
            uuid4(),
            uuid4(),
            [SubtitleSpec(text="x", start_ms=0, end_ms=100)],
        )
        # The response surfaces the flag so the FE can disable
        # "regenerate subtitles" buttons.
        assert result.refinement_source == "manual_edit"

    @pytest.mark.asyncio
    async def test_empty_subtitles_still_calls_repo(self) -> None:
        """Operator clearing all subtitles must still set manual_edit
        — otherwise a Whisper pass would re-fill them."""
        svc = _make_service_with_mocks()
        updated = _make_job(refinement_source="manual_edit", subtitles=[])
        svc.repository.update_subtitles_with_manual_edit = AsyncMock(
            return_value=updated
        )

        await svc.update_render_job_subtitles(uuid4(), uuid4(), uuid4(), [])

        svc.repository.update_subtitles_with_manual_edit.assert_awaited_once()
        args, _ = svc.repository.update_subtitles_with_manual_edit.call_args
        assert args[3] == []  # empty list reaches the repo


# ---- Repository-level shape tests (mocked session) ----


class TestRepositoryShape:
    @pytest.mark.asyncio
    async def test_builds_new_dict_not_in_place_mutation(self) -> None:
        """SQLAlchemy doesn't track JSONB internal mutation; the repo
        MUST assign a NEW dict to the column. Probe via the values()
        kwargs on the UPDATE statement."""
        from app.modules.shorts_render.repository import ShortsRenderJobRepository

        # Stub session returning a job, capturing the UPDATE call.
        captured_values: dict[str, Any] = {}

        class FakeSession:
            async def execute(self, stmt, *args, **kwargs):
                # SQLAlchemy Update statement: extract its compiled values
                if hasattr(stmt, "compile"):
                    compiled = stmt.compile()
                    captured_values.update(compiled.params)
                return MagicMock(scalar_one_or_none=lambda: None, rowcount=1)

            async def flush(self):
                return None

        original_input_spec = {
            "scene_clips": [{"video_id": "v", "scene_id": "s"}],
            "subtitles": [{"text": "old", "start_ms": 0, "end_ms": 100}],
            "title": "stays",
        }
        existing_job = _make_job(subtitles=original_input_spec["subtitles"])
        existing_job.input_spec = original_input_spec

        repo = ShortsRenderJobRepository(FakeSession())  # type: ignore[arg-type]
        repo.get_by_id = AsyncMock(return_value=existing_job)
        repo._get_by_id_internal = AsyncMock(return_value=existing_job)

        new_subs = [{"text": "fresh", "start_ms": 0, "end_ms": 500}]
        await repo.update_subtitles_with_manual_edit(
            uuid4(), uuid4(), uuid4(), new_subs
        )

        # The values dict on the UPDATE must include the rebuilt
        # input_spec (with new subtitles) and refinement_source set.
        new_spec = captured_values.get("input_spec")
        assert new_spec is not None
        assert new_spec["subtitles"] == new_subs
        # Non-subtitle fields preserved
        assert new_spec["scene_clips"] == original_input_spec["scene_clips"]
        assert new_spec["title"] == "stays"
        # Manual edit flag set in same UPDATE
        assert captured_values["refinement_source"] == "manual_edit"
        # Original ORM attribute NOT mutated
        assert original_input_spec["subtitles"] == [
            {"text": "old", "start_ms": 0, "end_ms": 100}
        ]
