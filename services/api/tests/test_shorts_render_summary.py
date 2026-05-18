"""Tests for the shorts_render summary endpoint.

Two layers:
  * pure-function tests for the prompt builder
  * service-level tests for ``ShortsRenderSummaryService.generate``'s
    cache/regenerate branching (migration 059 persistence) using
    inline fakes — no DB, no network.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.shorts_render.summary_prompt import (
    PROMPT_VERSION,
    _SYSTEM_PROMPT,
    _SceneSignals,
    build_user_prompt,
)
from app.modules.shorts_render.summary_service import (
    ShortsRenderSummaryService,
    SummaryNotReadyError,
)


class TestPromptVersion:
    def test_v1(self):
        assert PROMPT_VERSION == "v1"

    def test_system_prompt_mentions_evergreen(self):
        low = _SYSTEM_PROMPT.lower()
        assert "evergreen" in low
        assert "korean" in low
        # block-list keywords
        assert "오늘만" in _SYSTEM_PROMPT


class TestUserPromptBuilder:
    def test_includes_all_signals(self):
        scenes = [
            _SceneSignals(
                start_ms=0, end_ms=8000,
                transcript="이거 한번 보세요",
                scene_caption="여성 호스트가 마스크팩을 들고 있음",
                ocr_text="신상 마스크팩",
                speaker_transcript="이거 한번 보세요",
            ),
        ]
        out = build_user_prompt(
            scenes=scenes,
            target_duration_ms=8000,
            max_sentences=2,
        )
        assert "Clip length: 8s" in out
        assert "이거 한번 보세요" in out
        assert "여성 호스트" in out
        assert "신상 마스크팩" in out

    def test_chronological_order(self):
        scenes = [
            _SceneSignals(0, 5000, "first", "", "", ""),
            _SceneSignals(5000, 10000, "second", "", "", ""),
        ]
        out = build_user_prompt(
            scenes=scenes, target_duration_ms=10000, max_sentences=2,
        )
        first_idx = out.find("first")
        second_idx = out.find("second")
        assert 0 < first_idx < second_idx

    def test_joined_with_real_newlines(self):
        """Regression: build_user_prompt must join with an actual
        newline char, not the literal 2-char string ``\\n``."""
        scenes = [_SceneSignals(0, 5000, "alpha", "", "", "")]
        out = build_user_prompt(
            scenes=scenes, target_duration_ms=5000, max_sentences=2,
        )
        assert "\n" in out
        assert "\\n" not in out


# ---------- service-level: cache / regenerate branching (migration 059) ----------


class _RaisingOpenAI:
    """Fake AsyncOpenAI that fails the test if any call reaches it —
    used to prove the cache short-circuits before the network."""

    class _Chat:
        class _Completions:
            async def create(self, **_kwargs):
                raise AssertionError("OpenAI was called on a cache hit")

        def __init__(self):
            self.completions = _RaisingOpenAI._Chat._Completions()

    def __init__(self):
        self.chat = _RaisingOpenAI._Chat()


class _RaisingOSClient:
    """Fake SceneSearchClient that fails if queried — cache hit must
    not even fetch scenes."""

    async def get_video_scenes(self, **_kwargs):
        raise AssertionError("OpenSearch was queried on a cache hit")


class _StubOpenAI:
    """Fake AsyncOpenAI returning a fixed completion + usage."""

    class _Chat:
        class _Completions:
            def __init__(self, content: str):
                self._content = content
                self.calls = 0

            async def create(self, **_kwargs):
                self.calls += 1
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content=self._content)
                        )
                    ],
                    usage=SimpleNamespace(
                        prompt_tokens=500, completion_tokens=40
                    ),
                )

        def __init__(self, content: str):
            self.completions = _StubOpenAI._Chat._Completions(content)

    def __init__(self, content: str = "테스트 요약입니다."):
        self.chat = _StubOpenAI._Chat(content)


class _StubOSClient:
    """Fake SceneSearchClient — one page of scenes covering 0-20s."""

    def __init__(self):
        self.calls = 0

    async def get_video_scenes(self, *, org_id, video_id, page_size, offset):
        self.calls += 1
        if offset > 0:
            return {"scenes": []}
        return {
            "scenes": [
                {
                    "start_ms": 0,
                    "end_ms": 10_000,
                    "transcript_raw": "이 제품 정말 좋아요",
                    "scene_caption": "호스트가 제품을 들고 있음",
                    "ocr_text_raw": "신상품",
                    "speaker_transcript": "이 제품 정말 좋아요",
                },
                {
                    "start_ms": 10_000,
                    "end_ms": 20_000,
                    "transcript_raw": "촉촉하게 발려요",
                    "scene_caption": "제품 사용 장면",
                    "ocr_text_raw": "",
                    "speaker_transcript": "촉촉하게 발려요",
                },
            ]
        }


def _render_job(
    *,
    status: str = "completed",
    summary: str | None = None,
    summary_prompt_version: str | None = None,
    summary_generated_at: datetime | None = None,
):
    """Minimal duck-typed ShortsRenderJob for the service."""
    return SimpleNamespace(
        id=uuid4(),
        status=status,
        video_id="gd_test",
        input_spec={
            "scene_clips": [
                {
                    "video_id": "gd_test",
                    "start_ms": 0,
                    "end_ms": 20_000,
                }
            ]
        },
        summary=summary,
        summary_prompt_version=summary_prompt_version,
        summary_generated_at=summary_generated_at,
    )


class TestSummaryCacheBranching:
    @pytest.mark.asyncio
    async def test_cache_hit_skips_openai_and_opensearch(self):
        """summary set + version matches → from_cache=True, no
        OpenAI call, no OS query, cost 0."""
        job = _render_job(
            summary="기존 요약입니다.",
            summary_prompt_version="v1",
            summary_generated_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
        svc = ShortsRenderSummaryService(
            openai_client=_RaisingOpenAI(),
            os_client=_RaisingOSClient(),
            model="gpt-4o-mini",
            timeout_s=8.0,
            prompt_version="v1",
        )
        result = await svc.generate(org_id=uuid4(), render_job=job)
        assert result.from_cache is True
        assert result.summary == "기존 요약입니다."
        assert result.cost_usd == 0.0
        assert result.generated_at == datetime(
            2026, 5, 1, tzinfo=timezone.utc
        )

    @pytest.mark.asyncio
    async def test_version_mismatch_regenerates(self):
        """summary set but version differs → cache bypassed, OpenAI
        called, from_cache=False."""
        job = _render_job(
            summary="오래된 v0 요약.",
            summary_prompt_version="v0",
        )
        openai = _StubOpenAI(content="새로 생성된 요약.")
        svc = ShortsRenderSummaryService(
            openai_client=openai,
            os_client=_StubOSClient(),
            model="gpt-4o-mini",
            timeout_s=8.0,
            prompt_version="v1",  # current != job's v0
        )
        result = await svc.generate(org_id=uuid4(), render_job=job)
        assert result.from_cache is False
        assert result.summary == "새로 생성된 요약."
        assert result.prompt_version == "v1"
        assert openai.chat.completions.calls == 1

    @pytest.mark.asyncio
    async def test_null_summary_regenerates(self):
        """Legacy row (summary IS NULL) → regenerates."""
        job = _render_job(summary=None, summary_prompt_version=None)
        openai = _StubOpenAI()
        svc = ShortsRenderSummaryService(
            openai_client=openai,
            os_client=_StubOSClient(),
            model="gpt-4o-mini",
            timeout_s=8.0,
            prompt_version="v1",
        )
        result = await svc.generate(org_id=uuid4(), render_job=job)
        assert result.from_cache is False
        assert openai.chat.completions.calls == 1
        assert result.cost_usd > 0

    @pytest.mark.asyncio
    async def test_not_completed_raises_before_cache_check(self):
        """status != completed → SummaryNotReadyError even if a
        summary column somehow exists."""
        job = _render_job(
            status="rendering",
            summary="stale",
            summary_prompt_version="v1",
        )
        svc = ShortsRenderSummaryService(
            openai_client=_RaisingOpenAI(),
            os_client=_RaisingOSClient(),
            model="gpt-4o-mini",
            timeout_s=8.0,
            prompt_version="v1",
        )
        with pytest.raises(SummaryNotReadyError):
            await svc.generate(org_id=uuid4(), render_job=job)