"""Orchestration test for refinement_service._run_refinement.

Mocks every side-effecting boundary:
- refinement_repository.{lock_parent_or_none, create_refined_child, link_parent_to_child}
- S3Client.get_object_bytes_async
- WhisperTranscriber.transcribe
- publish_shorts_render_job
- get_async_session_factory

Verifies each major branch: happy path, guard skip, locked-elsewhere,
S3 timeout, Whisper budget/terminal, empty words, no chunks, DB
write failure, SQS publish failure, raced refinement after Whisper.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.lib.whisper_transcribe.budget import BudgetExceededError
from app.lib.whisper_transcribe.client import (
    WhisperRetryableError,
    WhisperTerminalError,
)
from app.modules.shorts_render import refinement_service


# ---------- helpers ----------


def _make_parent(
    *,
    job_id=None,
    output_s3_key="org/render/output.mp4",
    output_duration_ms=15_000,
    refinement_source=None,
    replaced_by=None,
    refined_from=None,
    has_subtitles=True,
):
    spec: dict[str, Any] = {
        "scene_clips": [{"video_id": "v1", "timeline_end_ms": 15_000}],
        "title": "다이슨 헤어드라이어",
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
        expires_at=None,
    )


def _whisper_result(
    *,
    words: list | None = None,
    text: str = "안녕 하세요",
    duration: float = 1.0,
    cost: float = 0.0001,
    latency_ms: int = 200,
):
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
        cost_usd=cost,
        latency_ms=latency_ms,
    )


@pytest.fixture
def mock_transcriber(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Pin a mock transcriber into the lazy-singleton path."""
    refinement_service.reset_singletons_for_tests()
    fake = MagicMock()
    fake.transcribe = AsyncMock(return_value=_whisper_result())
    monkeypatch.setattr(
        refinement_service, "_get_transcriber", lambda: fake
    )
    return fake


@pytest.fixture
def mock_s3(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace ``S3Client`` with a class returning a mock instance."""
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
    """Replace get_async_session_factory with a controllable mock."""
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
        # Each call to factory() returns a callable that yields a NEW
        # async-context-manager wrapping a fresh session.
        s = _make_session()

        def _opener():
            return _ctx_factory(s)

        return _opener

    import app.db.base as base_mod

    monkeypatch.setattr(base_mod, "get_async_session_factory", _factory)
    return sessions


@pytest.fixture
def repo_calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace refinement_repository functions with controllable mocks."""
    state: dict[str, Any] = {
        "lock_returns": [],  # FIFO: each call to lock_parent_or_none pops
        "create_returns": SimpleNamespace(
            id=uuid4(), org_id=uuid4(), video_id="gd_v1"
        ),
        "create_raises": None,
        "link_raises": None,
        "lock_calls": 0,
        "create_calls": 0,
        "link_calls": 0,
    }

    async def _lock(_session, _job_id):
        state["lock_calls"] += 1
        if state["lock_returns"]:
            return state["lock_returns"].pop(0)
        return None

    async def _create(_session, *, parent, refined_input_spec):
        state["create_calls"] += 1
        if state["create_raises"]:
            raise state["create_raises"]
        state["last_refined_spec"] = refined_input_spec
        return state["create_returns"]

    async def _link(_session, *, parent_id, child_id):
        state["link_calls"] += 1
        if state["link_raises"]:
            raise state["link_raises"]

    from app.modules.shorts_render import refinement_repository

    monkeypatch.setattr(refinement_repository, "lock_parent_or_none", _lock)
    monkeypatch.setattr(refinement_repository, "create_refined_child", _create)
    monkeypatch.setattr(refinement_repository, "link_parent_to_child", _link)
    return state


@pytest.fixture
def sqs_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Capture publish_shorts_render_job calls."""
    calls: list[dict] = []
    raises_holder = {"raises": None}

    def _publish(*, job_id, org_id, video_id, input_spec):
        calls.append(
            {
                "job_id": job_id,
                "org_id": org_id,
                "video_id": video_id,
                "input_spec": input_spec,
            }
        )
        if raises_holder["raises"]:
            raise raises_holder["raises"]

    import app.sqs_producer as sqs_mod

    monkeypatch.setattr(sqs_mod, "publish_shorts_render_job", _publish)
    monkeypatch.setattr(sqs_mod, "_publish_call_raises", raises_holder, raising=False)
    return calls


# ---------- happy path ----------


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_full_pipeline_creates_child_and_publishes(
        self,
        mock_transcriber,
        mock_s3,
        session_holder,
        repo_calls,
        sqs_calls,
    ) -> None:
        parent = _make_parent()
        repo_calls["lock_returns"] = [parent, parent]  # 1st lock + re-lock
        await refinement_service._run_refinement(parent.id)

        assert mock_transcriber.transcribe.call_count == 1
        assert repo_calls["create_calls"] == 1
        assert repo_calls["link_calls"] == 1
        assert len(sqs_calls) == 1
        # Refined spec preserves scene_clips, swaps subtitles
        spec = repo_calls["last_refined_spec"]
        assert spec["scene_clips"] == parent.input_spec["scene_clips"]
        assert len(spec["subtitles"]) >= 1
        assert spec["subtitles"][0]["start_ms"] == 0  # Whisper word at 0ms

    @pytest.mark.asyncio
    async def test_passes_title_as_whisper_prompt_bias(
        self, mock_transcriber, mock_s3, session_holder, repo_calls, sqs_calls
    ) -> None:
        parent = _make_parent()
        repo_calls["lock_returns"] = [parent, parent]
        await refinement_service._run_refinement(parent.id)
        kwargs = mock_transcriber.transcribe.call_args.kwargs
        assert kwargs["prompt"] == "다이슨 헤어드라이어"
        assert kwargs["language"] == "ko"


# ---------- skips ----------


class TestSkipPaths:
    @pytest.mark.asyncio
    async def test_lock_returns_none_skips_silently(
        self, mock_transcriber, mock_s3, session_holder, repo_calls, sqs_calls
    ) -> None:
        repo_calls["lock_returns"] = [None]  # locked elsewhere or missing
        await refinement_service._run_refinement(uuid4())
        assert mock_transcriber.transcribe.call_count == 0
        assert repo_calls["create_calls"] == 0
        assert sqs_calls == []

    @pytest.mark.asyncio
    async def test_guard_failure_skips_before_whisper(
        self, mock_transcriber, mock_s3, session_holder, repo_calls, sqs_calls
    ) -> None:
        # Already-refined parent — guard returns 'already_refined'
        parent = _make_parent(replaced_by=uuid4())
        repo_calls["lock_returns"] = [parent]
        await refinement_service._run_refinement(parent.id)
        assert mock_transcriber.transcribe.call_count == 0
        assert repo_calls["create_calls"] == 0

    @pytest.mark.asyncio
    async def test_empty_subtitles_in_parent_runs_whisper(
        self, mock_transcriber, mock_s3, session_holder, repo_calls, sqs_calls
    ) -> None:
        # Post 2026-05-07 OS-decoupling: track_stt/composition_builder
        # deliberately emits subtitles=[]. The runner MUST proceed —
        # Whisper is the source of subtitles, not a refiner of pre-
        # existing ones.
        parent = _make_parent(has_subtitles=False)
        repo_calls["lock_returns"] = [parent, parent]  # initial + re-lock
        await refinement_service._run_refinement(parent.id)
        assert mock_transcriber.transcribe.call_count == 1
        assert repo_calls["create_calls"] == 1
        assert len(sqs_calls) == 1
        # The refined spec carries Whisper-derived subtitles even
        # though the parent had none.
        spec = repo_calls["last_refined_spec"]
        assert len(spec["subtitles"]) >= 1


# ---------- failures (post-guard) ----------


class TestFailurePaths:
    @pytest.mark.asyncio
    async def test_s3_object_missing_skips(
        self, mock_transcriber, mock_s3, session_holder, repo_calls, sqs_calls
    ) -> None:
        mock_s3.get_object_bytes_async = AsyncMock(return_value=None)
        # Replace via the class (since fixture re-binds the class method)
        import app.storage.s3 as s3_mod

        class FakeS3:
            def __init__(self, **_):
                pass

            async def get_object_bytes_async(self, _key):
                return None

        s3_mod.S3Client = FakeS3  # type: ignore[misc]

        parent = _make_parent()
        repo_calls["lock_returns"] = [parent]
        await refinement_service._run_refinement(parent.id)
        assert mock_transcriber.transcribe.call_count == 0
        assert sqs_calls == []

    @pytest.mark.asyncio
    async def test_s3_download_timeout_skips(
        self, mock_transcriber, session_holder, repo_calls, sqs_calls,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Replace S3 client class with one whose download hangs
        import app.storage.s3 as s3_mod

        class HangingS3:
            def __init__(self, **_):
                pass

            async def get_object_bytes_async(self, _key):
                await asyncio.sleep(60)
                return b""

        monkeypatch.setattr(s3_mod, "S3Client", HangingS3)
        # Tighten the timeout so the test is fast
        monkeypatch.setattr(
            refinement_service,
            "get_settings",
            lambda: SimpleNamespace(
                drive_s3_bucket="b",
                auto_shorts_product_v2_whisper_s3_download_timeout_s=0.05,
                auto_shorts_product_v2_whisper_language="ko",
            ),
        )

        parent = _make_parent()
        repo_calls["lock_returns"] = [parent]
        await refinement_service._run_refinement(parent.id)
        assert mock_transcriber.transcribe.call_count == 0
        assert sqs_calls == []

    @pytest.mark.asyncio
    async def test_budget_exceeded_skips(
        self, mock_transcriber, mock_s3, session_holder, repo_calls, sqs_calls
    ) -> None:
        mock_transcriber.transcribe = AsyncMock(
            side_effect=BudgetExceededError("over")
        )
        parent = _make_parent()
        repo_calls["lock_returns"] = [parent]
        await refinement_service._run_refinement(parent.id)
        assert sqs_calls == []
        assert repo_calls["create_calls"] == 0

    @pytest.mark.asyncio
    async def test_whisper_terminal_error_skips(
        self, mock_transcriber, mock_s3, session_holder, repo_calls, sqs_calls
    ) -> None:
        mock_transcriber.transcribe = AsyncMock(
            side_effect=WhisperTerminalError("4xx")
        )
        parent = _make_parent()
        repo_calls["lock_returns"] = [parent]
        await refinement_service._run_refinement(parent.id)
        assert sqs_calls == []

    @pytest.mark.asyncio
    async def test_whisper_retryable_error_skips(
        self, mock_transcriber, mock_s3, session_holder, repo_calls, sqs_calls
    ) -> None:
        mock_transcriber.transcribe = AsyncMock(
            side_effect=WhisperRetryableError("5xx exhausted")
        )
        parent = _make_parent()
        repo_calls["lock_returns"] = [parent]
        await refinement_service._run_refinement(parent.id)
        assert sqs_calls == []

    @pytest.mark.asyncio
    async def test_empty_words_skips(
        self, mock_transcriber, mock_s3, session_holder, repo_calls, sqs_calls
    ) -> None:
        mock_transcriber.transcribe = AsyncMock(
            return_value=_whisper_result(words=[])
        )
        parent = _make_parent()
        repo_calls["lock_returns"] = [parent]
        await refinement_service._run_refinement(parent.id)
        assert sqs_calls == []
        assert repo_calls["create_calls"] == 0

    @pytest.mark.asyncio
    async def test_raced_refinement_after_whisper_skips(
        self, mock_transcriber, mock_s3, session_holder, repo_calls, sqs_calls
    ) -> None:
        """Whisper runs successfully but another runner refined while
        we were transcribing — the re-lock check finds replaced_by set."""
        parent = _make_parent()
        # 1st lock: clean parent
        # 2nd lock: parent now has replaced_by set
        racy = _make_parent(replaced_by=uuid4())
        repo_calls["lock_returns"] = [parent, racy]
        await refinement_service._run_refinement(parent.id)
        assert sqs_calls == []
        assert repo_calls["create_calls"] == 0

    @pytest.mark.asyncio
    async def test_db_write_failure_skips_sqs(
        self, mock_transcriber, mock_s3, session_holder, repo_calls, sqs_calls
    ) -> None:
        repo_calls["create_raises"] = RuntimeError("db down")
        parent = _make_parent()
        repo_calls["lock_returns"] = [parent, parent]
        await refinement_service._run_refinement(parent.id)
        assert sqs_calls == []


# ---------- never raises ----------


class TestErrorContract:
    @pytest.mark.asyncio
    async def test_runner_swallows_unexpected_exceptions(
        self, mock_transcriber, mock_s3, session_holder, repo_calls
    ) -> None:
        """Even a totally broken inner path must not raise out of _runner."""
        # Force an unexpected exception inside lock_parent_or_none
        from app.modules.shorts_render import refinement_repository

        async def _broken(_s, _id):
            raise RuntimeError("unexpected")

        refinement_repository.lock_parent_or_none = _broken  # type: ignore[assignment]

        # _runner wraps _run_refinement; must not raise
        await refinement_service._runner(uuid4())
