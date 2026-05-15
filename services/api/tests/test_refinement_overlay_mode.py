"""Tests for the overlay-mode branch of refinement_service._run_refinement.

Plan: ``.claude/plans/auto-shorts-overlay-mode-2026-05-07.md``.

When ``auto_shorts_product_v2_overlay_mode_enabled`` is True the runner
must:
  * UPDATE the parent's ``input_spec.subtitles`` in place (via
    ``persist_overlay_subtitles_on_parent``).
  * NOT create a child render row.
  * NOT call ``link_parent_to_child``.
  * NOT publish to SQS.
  * Skip on a re-lock when ``parent.refinement_source`` is already set
    (race condition: another runner persisted before us).

When the flag is False, behavior is unchanged from PR 4 (existing tests
in ``test_refinement_service_runner.py`` cover that path).

The guard adjustment is also covered: ``_check_guards`` returns
``'whisper_overlay'`` when ``parent.refinement_source == 'whisper'``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.shorts_render import refinement_service


# ---------- shared fixtures (mirrors test_refinement_service_runner) ----------


def _make_parent(
    *,
    job_id=None,
    output_s3_key="org/render/output.mp4",
    output_duration_ms=15_000,
    refinement_source=None,
    replaced_by=None,
    refined_from=None,
    has_subtitles=False,
):
    spec: dict[str, Any] = {
        "scene_clips": [{"video_id": "v1", "timeline_end_ms": 15_000}],
        "title": "다이슨 헤어드라이어",
        "output": {"width": 406, "height": 720},
    }
    if has_subtitles:
        spec["subtitles"] = [
            {"text": "안녕", "start_ms": 0, "end_ms": 1000, "style": {"k": "v"}}
        ]
    return SimpleNamespace(
        id=job_id or uuid4(),
        org_id=uuid4(),
        user_id=uuid4(),
        video_id="gd_v1",
        title="다이슨 헤어드라이어",
        output_s3_key=output_s3_key,
        output_duration_ms=output_duration_ms,
        input_spec=spec,
        refinement_source=refinement_source,
        replaced_by_render_job_id=replaced_by,
        refined_from_render_job_id=refined_from,
        summary=None,
        summary_prompt_version=None,
        summary_generated_at=None,
        expires_at=None,
    )


def _whisper_result(*, words=None, text="안녕 하세요", duration=1.0):
    from app.lib.whisper_transcribe.schemas import WhisperResult, WhisperWord

    if words is None:
        words = [
            WhisperWord(word="안녕", start_ms=0, end_ms=400),
            WhisperWord(word="하세요", start_ms=450, end_ms=900),
        ]
    return WhisperResult(
        words=tuple(words),
        text=text,
        language="ko",
        duration_seconds=duration,
        cost_usd=0.0001,
        latency_ms=200,
    )


@pytest.fixture
def overlay_mode_on(monkeypatch: pytest.MonkeyPatch):
    """Force overlay-mode flag ON for the duration of the test."""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "auto_shorts_product_v2_overlay_mode_enabled",
        True,
        raising=False,
    )


@pytest.fixture
def overlay_mode_off(monkeypatch: pytest.MonkeyPatch):
    """Force overlay-mode flag OFF (legacy path)."""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "auto_shorts_product_v2_overlay_mode_enabled",
        False,
        raising=False,
    )


@pytest.fixture
def mock_transcriber(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    refinement_service.reset_singletons_for_tests()
    fake = MagicMock()
    fake.transcribe = AsyncMock(return_value=_whisper_result())
    monkeypatch.setattr(refinement_service, "_get_transcriber", lambda: fake)
    return fake


@pytest.fixture
def mock_s3(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    instance = MagicMock()
    instance.get_object_bytes_async = AsyncMock(return_value=b"\x00\x01\x02")

    class FakeS3Client:
        def __init__(self, **_kwargs):
            pass

        get_object_bytes_async = instance.get_object_bytes_async

    import app.storage.s3 as s3_mod
    monkeypatch.setattr(s3_mod, "S3Client", FakeS3Client)
    return instance


@pytest.fixture
def session_holder(monkeypatch: pytest.MonkeyPatch):
    sessions: list[AsyncMock] = []

    def _make_session() -> AsyncMock:
        s = AsyncMock()
        s.commit = AsyncMock()
        s.rollback = AsyncMock()
        s.close = AsyncMock()
        sessions.append(s)
        return s

    @asynccontextmanager
    async def _ctx_factory(_session: AsyncMock):
        try:
            yield _session
        finally:
            await _session.close()

    def _factory():
        s = _make_session()

        def _opener():
            return _ctx_factory(s)

        return _opener

    import app.db.base as base_mod
    monkeypatch.setattr(base_mod, "get_async_session_factory", _factory)
    return sessions


@pytest.fixture
def repo_calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {
        "lock_returns": [],
        "create_returns": SimpleNamespace(
            id=uuid4(), org_id=uuid4(), video_id="gd_v1"
        ),
        "lock_calls": 0,
        "create_calls": 0,
        "link_calls": 0,
        "persist_calls": 0,
        "last_refined_spec": None,
        "last_persist_args": None,
    }

    async def _lock(_session, _job_id):
        state["lock_calls"] += 1
        if state["lock_returns"]:
            return state["lock_returns"].pop(0)
        return None

    async def _create(_session, *, parent, refined_input_spec):
        state["create_calls"] += 1
        state["last_refined_spec"] = refined_input_spec
        return state["create_returns"]

    async def _link(_session, *, parent_id, child_id):
        state["link_calls"] += 1

    async def _persist(_session, *, parent_id, refined_input_spec):
        state["persist_calls"] += 1
        state["last_persist_args"] = {
            "parent_id": parent_id,
            "refined_input_spec": refined_input_spec,
        }

    from app.modules.shorts_render import refinement_repository
    monkeypatch.setattr(refinement_repository, "lock_parent_or_none", _lock)
    monkeypatch.setattr(refinement_repository, "create_refined_child", _create)
    monkeypatch.setattr(refinement_repository, "link_parent_to_child", _link)
    monkeypatch.setattr(
        refinement_repository,
        "persist_overlay_subtitles_on_parent",
        _persist,
    )
    return state


@pytest.fixture
def sqs_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []

    def _publish(*, job_id, org_id, video_id, input_spec):
        calls.append(
            {"job_id": job_id, "org_id": org_id, "video_id": video_id,
             "input_spec": input_spec}
        )

    import app.sqs_producer as sqs_mod
    monkeypatch.setattr(sqs_mod, "publish_shorts_render_job", _publish)
    return calls


# ---------- overlay-mode happy path ----------


class TestOverlayModePersist:
    @pytest.mark.asyncio
    async def test_persists_to_parent_no_child_no_sqs(
        self,
        overlay_mode_on,
        mock_transcriber,
        mock_s3,
        session_holder,
        repo_calls,
        sqs_calls,
    ) -> None:
        parent = _make_parent(has_subtitles=False)
        repo_calls["lock_returns"] = [parent, parent]  # initial + re-lock

        await refinement_service._run_refinement(parent.id)

        # Whisper still ran: same transcribe pipeline up through the
        # spec build.
        assert mock_transcriber.transcribe.call_count == 1

        # Persisted to parent in place.
        assert repo_calls["persist_calls"] == 1
        persist = repo_calls["last_persist_args"]
        assert persist is not None
        assert persist["parent_id"] == parent.id
        spec = persist["refined_input_spec"]
        assert spec["scene_clips"] == parent.input_spec["scene_clips"]
        assert len(spec["subtitles"]) >= 1
        assert spec["subtitles"][0]["start_ms"] == 0

        # No child + no link + no SQS publish.
        assert repo_calls["create_calls"] == 0
        assert repo_calls["link_calls"] == 0
        assert sqs_calls == []

    @pytest.mark.asyncio
    async def test_skips_when_already_overlay_persisted_in_race(
        self,
        overlay_mode_on,
        mock_transcriber,
        mock_s3,
        session_holder,
        repo_calls,
        sqs_calls,
    ) -> None:
        # First lock: clean parent (passes guards). Re-lock: another
        # runner already persisted (refinement_source='whisper'). The
        # overlay-mode race check skips.
        parent_pass = _make_parent(has_subtitles=False)
        parent_raced = _make_parent(
            job_id=parent_pass.id,
            has_subtitles=False,
            refinement_source="whisper",
        )
        repo_calls["lock_returns"] = [parent_pass, parent_raced]

        await refinement_service._run_refinement(parent_pass.id)

        assert mock_transcriber.transcribe.call_count == 1
        assert repo_calls["persist_calls"] == 0
        assert repo_calls["create_calls"] == 0


class TestOverlayModeOffStillUsesChildPath:
    @pytest.mark.asyncio
    async def test_off_mode_unchanged(
        self,
        overlay_mode_off,
        mock_transcriber,
        mock_s3,
        session_holder,
        repo_calls,
        sqs_calls,
    ) -> None:
        parent = _make_parent(has_subtitles=False)
        repo_calls["lock_returns"] = [parent, parent]

        await refinement_service._run_refinement(parent.id)

        assert mock_transcriber.transcribe.call_count == 1
        assert repo_calls["persist_calls"] == 0
        assert repo_calls["create_calls"] == 1
        assert repo_calls["link_calls"] == 1
        assert len(sqs_calls) == 1


# ---------- guard ----------


class TestCheckGuardsWhisperOverlay:
    def test_whisper_source_returns_whisper_overlay(self) -> None:
        parent = _make_parent(refinement_source="whisper")
        reason = refinement_service._check_guards(parent)
        assert reason == "whisper_overlay"

    def test_manual_edit_still_returns_manual_edit(self) -> None:
        parent = _make_parent(refinement_source="manual_edit")
        reason = refinement_service._check_guards(parent)
        assert reason == "manual_edit"

    def test_replaced_by_still_returns_already_refined(self) -> None:
        parent = _make_parent(replaced_by=uuid4())
        reason = refinement_service._check_guards(parent)
        assert reason == "already_refined"

    def test_refined_from_still_returns_refined_from(self) -> None:
        parent = _make_parent(refined_from=uuid4())
        reason = refinement_service._check_guards(parent)
        assert reason == "refined_from"

    def test_clean_parent_returns_none(self) -> None:
        parent = _make_parent()
        assert refinement_service._check_guards(parent) is None
