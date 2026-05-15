"""Async Whisper client behaviour with a mocked OpenAI SDK."""

from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.lib.whisper_transcribe.budget import (
    BudgetExceededError,
    InMemoryBudgetTracker,
)
from app.lib.whisper_transcribe.client import (
    WhisperRetryableError,
    WhisperTerminalError,
    WhisperTranscriber,
    _estimated_cost_usd,
    _parse_words,
)


# ---------- helpers ----------


def _whisper_response(
    *,
    text: str = "안녕 하세요",
    language: str = "ko",
    duration: float = 1.0,
    words: list[dict[str, Any]] | None = None,
) -> SimpleNamespace:
    """Build a fake response matching the OpenAI SDK shape."""
    if words is None:
        words = [
            {"word": "안녕", "start": 0.0, "end": 0.4},
            {"word": "하세요", "start": 0.4, "end": 0.9},
        ]
    word_objs = [SimpleNamespace(**w) for w in words]
    return SimpleNamespace(
        text=text,
        language=language,
        duration=duration,
        words=word_objs,
    )


def _build_transcriber(
    *,
    daily_budget_usd: float = 1.0,
    timeout_s: float = 5.0,
    max_retries: int = 2,
) -> tuple[WhisperTranscriber, MagicMock, InMemoryBudgetTracker]:
    """Build a transcriber with its OpenAI client replaced by a mock.

    Returns ``(transcriber, mock_create, budget_tracker)`` so individual
    tests can assert against the create kwargs and the budget state.
    """
    budget = InMemoryBudgetTracker(daily_budget_usd=daily_budget_usd)
    transcriber = WhisperTranscriber(
        api_key="test-key",
        budget_tracker=budget,
        timeout_s=timeout_s,
        max_retries=max_retries,
        backoff_base_s=0.0,  # zero so retry tests don't sleep
        backoff_max_s=0.0,
    )
    mock_client = MagicMock()
    mock_create = AsyncMock(return_value=_whisper_response())
    mock_client.audio.transcriptions.create = mock_create
    transcriber._client = mock_client  # type: ignore[assignment]
    return transcriber, mock_create, budget


# ---------- construction ----------


class TestConstruction:
    def test_empty_api_key_raises(self) -> None:
        with pytest.raises(ValueError, match="API key"):
            WhisperTranscriber(
                api_key="",
                budget_tracker=InMemoryBudgetTracker(daily_budget_usd=1.0),
            )

    def test_default_model_is_whisper_1(self) -> None:
        t = WhisperTranscriber(
            api_key="x",
            budget_tracker=InMemoryBudgetTracker(daily_budget_usd=1.0),
        )
        assert t.model == "whisper-1"


# ---------- request shape ----------


class TestRequestShape:
    @pytest.mark.asyncio
    async def test_passes_required_kwargs_to_openai_sdk(self) -> None:
        transcriber, mock_create, _ = _build_transcriber()
        await transcriber.transcribe(
            audio_bytes=b"\x00\x01\x02",
            audio_duration_seconds=2.0,
            language="ko",
        )

        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        assert kwargs["model"] == "whisper-1"
        assert kwargs["response_format"] == "verbose_json"
        assert kwargs["timestamp_granularities"] == ["word"]
        assert kwargs["language"] == "ko"
        # File parameter is BytesIO with .name attribute the SDK uses
        # for content-type sniffing.
        file_arg = kwargs["file"]
        assert isinstance(file_arg, io.BytesIO)
        assert file_arg.name == "audio.mp4"
        # No prompt by default
        assert "prompt" not in kwargs

    @pytest.mark.asyncio
    async def test_prompt_passed_when_provided(self) -> None:
        transcriber, mock_create, _ = _build_transcriber()
        await transcriber.transcribe(
            audio_bytes=b"\x00",
            audio_duration_seconds=1.0,
            prompt="제품: 다이슨 헤어드라이어",
        )
        kwargs = mock_create.call_args.kwargs
        assert kwargs["prompt"] == "제품: 다이슨 헤어드라이어"

    @pytest.mark.asyncio
    async def test_filename_override(self) -> None:
        transcriber, mock_create, _ = _build_transcriber()
        await transcriber.transcribe(
            audio_bytes=b"\x00",
            audio_duration_seconds=1.0,
            filename="clip.m4a",
        )
        assert mock_create.call_args.kwargs["file"].name == "clip.m4a"

    @pytest.mark.asyncio
    async def test_empty_audio_raises_before_api_call(self) -> None:
        transcriber, mock_create, _ = _build_transcriber()
        with pytest.raises(ValueError, match="non-empty"):
            await transcriber.transcribe(
                audio_bytes=b"", audio_duration_seconds=1.0
            )
        mock_create.assert_not_called()


# ---------- response parsing ----------


class TestResponseParsing:
    @pytest.mark.asyncio
    async def test_parses_words_into_milliseconds(self) -> None:
        transcriber, mock_create, _ = _build_transcriber()
        mock_create.return_value = _whisper_response(
            words=[
                {"word": "hello", "start": 0.05, "end": 0.5},
                {"word": "world", "start": 0.6, "end": 1.0},
            ]
        )
        result = await transcriber.transcribe(
            audio_bytes=b"\x00", audio_duration_seconds=1.0
        )
        assert len(result.words) == 2
        assert result.words[0].word == "hello"
        assert result.words[0].start_ms == 50
        assert result.words[0].end_ms == 500
        assert result.words[1].start_ms == 600
        assert result.words[1].end_ms == 1000

    @pytest.mark.asyncio
    async def test_handles_dict_response_shape(self) -> None:
        """Some SDK versions return dicts, not Pydantic models."""
        transcriber, mock_create, _ = _build_transcriber()
        mock_create.return_value = {
            "text": "hi",
            "language": "en",
            "duration": 0.5,
            "words": [{"word": "hi", "start": 0.0, "end": 0.4}],
        }
        result = await transcriber.transcribe(
            audio_bytes=b"\x00", audio_duration_seconds=0.5
        )
        assert result.text == "hi"
        assert result.language == "en"
        assert len(result.words) == 1

    @pytest.mark.asyncio
    async def test_clamps_inverted_word_timestamps(self) -> None:
        """Whisper occasionally emits end < start; we clamp not raise."""
        transcriber, mock_create, _ = _build_transcriber()
        mock_create.return_value = _whisper_response(
            words=[{"word": "x", "start": 1.0, "end": 0.9}]
        )
        result = await transcriber.transcribe(
            audio_bytes=b"\x00", audio_duration_seconds=1.0
        )
        assert len(result.words) == 1
        assert result.words[0].start_ms == 1000
        assert result.words[0].end_ms == 1000  # clamped to start_ms

    @pytest.mark.asyncio
    async def test_drops_empty_word_strings(self) -> None:
        transcriber, mock_create, _ = _build_transcriber()
        mock_create.return_value = _whisper_response(
            words=[
                {"word": "", "start": 0.0, "end": 0.1},
                {"word": "ok", "start": 0.1, "end": 0.5},
                {"word": "   ", "start": 0.5, "end": 0.6},
            ]
        )
        result = await transcriber.transcribe(
            audio_bytes=b"\x00", audio_duration_seconds=0.6
        )
        assert [w.word for w in result.words] == ["ok"]

    @pytest.mark.asyncio
    async def test_empty_words_yields_empty_tuple(self) -> None:
        transcriber, mock_create, _ = _build_transcriber()
        mock_create.return_value = _whisper_response(
            text="",
            words=[],
        )
        result = await transcriber.transcribe(
            audio_bytes=b"\x00", audio_duration_seconds=1.0
        )
        assert result.words == ()
        assert result.text == ""

    def test_parse_words_handles_missing_words_attribute(self) -> None:
        """Defensive: response with no words[] returns empty tuple."""
        assert _parse_words(SimpleNamespace(text="x")) == ()
        assert _parse_words({"text": "x"}) == ()


# ---------- budget integration ----------


class TestBudgetIntegration:
    @pytest.mark.asyncio
    async def test_records_actual_cost_from_api_duration(self) -> None:
        transcriber, mock_create, budget = _build_transcriber()
        # Caller estimated 2s, API reports 5s — record uses API duration.
        mock_create.return_value = _whisper_response(duration=5.0)
        result = await transcriber.transcribe(
            audio_bytes=b"\x00", audio_duration_seconds=2.0
        )
        # whisper-1: $0.006/min × 5s = $0.0005
        expected = _estimated_cost_usd("whisper-1", 5.0)
        assert result.cost_usd == pytest.approx(expected)
        assert budget.spent_today_usd() == pytest.approx(expected)

    @pytest.mark.asyncio
    async def test_budget_exceeded_blocks_pre_call(self) -> None:
        transcriber, mock_create, budget = _build_transcriber(
            daily_budget_usd=0.00001
        )
        with pytest.raises(BudgetExceededError):
            await transcriber.transcribe(
                audio_bytes=b"\x00",
                audio_duration_seconds=60.0,  # ~$0.006 estimated
            )
        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_terminal_error_releases_reservation(self) -> None:
        transcriber, mock_create, budget = _build_transcriber()

        # Use plain ValueError with a status_code attr (mimics 4xx response).
        class FakeBadRequest(Exception):
            status_code = 400

        mock_create.side_effect = FakeBadRequest("bad request")
        with pytest.raises(WhisperTerminalError):
            await transcriber.transcribe(
                audio_bytes=b"\x00", audio_duration_seconds=1.0
            )
        # Reservation was released, no spend recorded
        assert budget.spent_today_usd() == 0.0
        # Full budget still available
        budget.check_and_reserve(1.0)


# ---------- retry + error classification ----------


class TestRetryBehaviour:
    @pytest.mark.asyncio
    async def test_retries_on_retryable_error_then_succeeds(self) -> None:
        transcriber, mock_create, _ = _build_transcriber(max_retries=3)

        class FakeRateLimit(Exception):
            status_code = 429

        mock_create.side_effect = [
            FakeRateLimit("rate limit"),
            FakeRateLimit("rate limit"),
            _whisper_response(),
        ]
        result = await transcriber.transcribe(
            audio_bytes=b"\x00", audio_duration_seconds=1.0
        )
        assert result.text == "안녕 하세요"
        assert mock_create.call_count == 3

    @pytest.mark.asyncio
    async def test_terminal_error_does_not_retry(self) -> None:
        transcriber, mock_create, _ = _build_transcriber(max_retries=3)

        class FakeAuthError(Exception):
            status_code = 401

        mock_create.side_effect = FakeAuthError("unauthorized")
        with pytest.raises(WhisperTerminalError):
            await transcriber.transcribe(
                audio_bytes=b"\x00", audio_duration_seconds=1.0
            )
        # Exactly one call — no retries on terminal.
        assert mock_create.call_count == 1

    @pytest.mark.asyncio
    async def test_retries_exhausted_raises_retryable(self) -> None:
        transcriber, mock_create, budget = _build_transcriber(max_retries=2)

        class FakeServerError(Exception):
            status_code = 503

        mock_create.side_effect = FakeServerError("upstream down")
        with pytest.raises(WhisperRetryableError):
            await transcriber.transcribe(
                audio_bytes=b"\x00", audio_duration_seconds=1.0
            )
        # 1 initial attempt + 2 retries = 3 calls
        assert mock_create.call_count == 3
        # Reservation released
        assert budget.spent_today_usd() == 0.0
        budget.check_and_reserve(1.0)

    @pytest.mark.asyncio
    async def test_each_retry_uses_fresh_buffer(self) -> None:
        """The SDK consumes the file stream on send; retrying with the
        same exhausted BytesIO would upload zero bytes."""
        transcriber, mock_create, _ = _build_transcriber(max_retries=2)

        class FakeServerError(Exception):
            status_code = 502

        mock_create.side_effect = [
            FakeServerError("nope"),
            _whisper_response(),
        ]
        await transcriber.transcribe(
            audio_bytes=b"\x01\x02\x03",
            audio_duration_seconds=1.0,
        )
        # Each call got a different BytesIO instance with the bytes
        # readable (position 0).
        first_call_buf = mock_create.call_args_list[0].kwargs["file"]
        second_call_buf = mock_create.call_args_list[1].kwargs["file"]
        assert first_call_buf is not second_call_buf
        # Both buffers contain the original bytes
        first_call_buf.seek(0)
        second_call_buf.seek(0)
        assert first_call_buf.read() == b"\x01\x02\x03"
        assert second_call_buf.read() == b"\x01\x02\x03"


class TestTimeout:
    @pytest.mark.asyncio
    async def test_per_call_timeout_classified_as_terminal(self) -> None:
        """asyncio.TimeoutError on wait_for is terminal (caller falls back)."""
        transcriber, mock_create, _ = _build_transcriber(
            timeout_s=0.05, max_retries=3
        )

        async def hang(**_kwargs: Any) -> Any:
            await asyncio.sleep(10)
            return _whisper_response()

        mock_create.side_effect = hang
        with pytest.raises(WhisperTerminalError):
            await transcriber.transcribe(
                audio_bytes=b"\x00", audio_duration_seconds=1.0
            )


class TestCostEstimation:
    def test_whisper_1_per_second_rate(self) -> None:
        # $0.006/min = $0.0001/sec
        assert _estimated_cost_usd("whisper-1", 60.0) == pytest.approx(0.006)
        assert _estimated_cost_usd("whisper-1", 1.0) == pytest.approx(0.0001)

    def test_zero_duration_costs_zero(self) -> None:
        assert _estimated_cost_usd("whisper-1", 0.0) == 0.0

    def test_negative_duration_clamped_to_zero(self) -> None:
        assert _estimated_cost_usd("whisper-1", -5.0) == 0.0

    def test_unknown_model_falls_back_to_whisper_1_rate(self) -> None:
        # We don't want unpriced models to be free (would underbill).
        assert _estimated_cost_usd("whisper-future-v2", 60.0) == pytest.approx(
            0.006
        )
