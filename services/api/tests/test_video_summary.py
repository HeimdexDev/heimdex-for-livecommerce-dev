"""Tests for video summary module: openai_client, prompts, schemas."""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.video_summary.openai_client import compute_input_hash, generate_video_summary
from app.modules.video_summary.prompts import CURRENT_VERSION, PROMPTS, get_prompt
from app.modules.video_summary.schemas import (
    VideoSummaryEditRequest,
    VideoSummaryGenerateRequest,
    VideoSummaryResponse,
)


# --- compute_input_hash ---


class TestComputeInputHash:
    def test_deterministic(self):
        captions = ["a", "b", "c"]
        h1 = compute_input_hash(captions)
        h2 = compute_input_hash(captions)
        assert h1 == h2

    def test_order_insensitive(self):
        """Hash sorts captions, so order doesn't matter."""
        h1 = compute_input_hash(["b", "a", "c"])
        h2 = compute_input_hash(["a", "b", "c"])
        assert h1 == h2

    def test_different_content_different_hash(self):
        h1 = compute_input_hash(["red dress"])
        h2 = compute_input_hash(["blue dress"])
        assert h1 != h2

    def test_empty_list(self):
        h = compute_input_hash([])
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex length

    def test_returns_sha256(self):
        captions = ["hello"]
        expected = hashlib.sha256("hello".encode("utf-8")).hexdigest()
        assert compute_input_hash(captions) == expected


# --- generate_video_summary ---


class TestGenerateVideoSummary:
    @pytest.mark.asyncio
    async def test_calls_openai_with_correct_params(self):
        mock_client = AsyncMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "요약 결과"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        result = await generate_video_summary(
            client=mock_client,
            video_title="테스트 영상",
            scene_captions=["장면1 설명", "장면2 설명"],
            system_prompt="test system",
            user_template="제목: {video_title}\n{scene_count}개\n{numbered_captions}",
            model="gpt-4o-mini",
            max_tokens=300,
        )

        assert result == "요약 결과"
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4o-mini"
        assert call_kwargs["max_tokens"] == 300
        assert len(call_kwargs["messages"]) == 2
        assert call_kwargs["messages"][0]["role"] == "system"
        assert "테스트 영상" in call_kwargs["messages"][1]["content"]
        assert "장면1 설명" in call_kwargs["messages"][1]["content"]

    @pytest.mark.asyncio
    async def test_handles_none_content(self):
        mock_client = AsyncMock()
        mock_choice = MagicMock()
        mock_choice.message.content = None
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        result = await generate_video_summary(
            client=mock_client,
            video_title="test",
            scene_captions=["cap"],
            system_prompt="sys",
            user_template="{video_title} {scene_count} {numbered_captions}",
        )

        assert result == ""

    @pytest.mark.asyncio
    async def test_strips_whitespace(self):
        mock_client = AsyncMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "  요약 결과\n  "
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        result = await generate_video_summary(
            client=mock_client,
            video_title="test",
            scene_captions=["cap"],
            system_prompt="sys",
            user_template="{video_title} {scene_count} {numbered_captions}",
        )

        assert result == "요약 결과"

    @pytest.mark.asyncio
    async def test_numbered_captions_format(self):
        mock_client = AsyncMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "ok"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        await generate_video_summary(
            client=mock_client,
            video_title="t",
            scene_captions=["first", "second", "third"],
            system_prompt="s",
            user_template="{video_title} {scene_count} {numbered_captions}",
        )

        user_msg = mock_client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        assert "1. first" in user_msg
        assert "2. second" in user_msg
        assert "3. third" in user_msg

    @pytest.mark.asyncio
    async def test_no_title_uses_fallback(self):
        mock_client = AsyncMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "ok"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        await generate_video_summary(
            client=mock_client,
            video_title="",
            scene_captions=["cap"],
            system_prompt="s",
            user_template="{video_title} {scene_count} {numbered_captions}",
        )

        user_msg = mock_client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        assert "(제목 없음)" in user_msg


# --- Prompts ---


class TestPrompts:
    def test_current_version_exists(self):
        prompt = get_prompt(CURRENT_VERSION)
        assert prompt.system
        assert prompt.user_template

    def test_all_versions_have_required_placeholders(self):
        for version, prompt in PROMPTS.items():
            assert "{video_title}" in prompt.user_template, f"{version} missing video_title"
            assert "{scene_count}" in prompt.user_template, f"{version} missing scene_count"
            assert "{numbered_captions}" in prompt.user_template, f"{version} missing numbered_captions"

    def test_unknown_version_raises(self):
        with pytest.raises(ValueError, match="Unknown prompt version"):
            get_prompt("v999")

    def test_v1_system_prompt_is_korean_focused(self):
        prompt = get_prompt("v1")
        assert "Korean" in prompt.system
        assert "2-4 sentences" in prompt.system


# --- Schemas ---


class TestSchemas:
    def test_response_defaults(self):
        resp = VideoSummaryResponse(video_id="v1", summary="test")
        assert resp.is_edited is False
        assert resp.is_stale is False
        assert resp.scene_count == 0

    def test_edit_request_validation(self):
        req = VideoSummaryEditRequest(summary="hello")
        assert req.summary == "hello"

    def test_edit_request_rejects_empty(self):
        with pytest.raises(Exception):
            VideoSummaryEditRequest(summary="")

    def test_generate_request_defaults(self):
        req = VideoSummaryGenerateRequest()
        assert req.force is False
