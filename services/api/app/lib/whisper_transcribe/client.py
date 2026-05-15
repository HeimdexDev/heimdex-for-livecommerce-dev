"""Async OpenAI Whisper client.

Mirrors the structure of ``app/modules/shorts_auto/llm/client.py``:
- ``AsyncOpenAI`` once per process.
- ``asyncio.wait_for`` enforces hard per-call timeout.
- Bounded retries on 429 / 5xx with exponential backoff.
- Pre-call budget reservation, post-call spend record (released on
  pre-call failure to avoid reservation leaks).
- Error contract: ``WhisperTerminalError`` (4xx, do not retry),
  ``WhisperRetryableError`` (retries exhausted),
  ``BudgetExceededError`` (daily cap, raised from ``.budget``).

Whisper-specific deviations from the LLM client:
- Endpoint is ``client.audio.transcriptions.create``, not
  ``chat.completions``. Different request/response shape.
- Cost is per-second of audio (whisper-1: $0.006/min). We charge
  ``audio_duration_seconds`` × rate, not token usage.
- Response parsing extracts ``words[]`` from ``verbose_json``.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
from typing import Any

from app.lib.whisper_transcribe.budget import BudgetTracker
from app.lib.whisper_transcribe.schemas import WhisperResult, WhisperWord

logger = logging.getLogger(__name__)


# whisper-1 pricing as of 2026-05-06 ($0.006 per minute → per second).
# OpenAI bills rounded up to the nearest second per their docs;
# we mirror that with ``math.ceil`` at cost-record time.
_WHISPER_USD_PER_SECOND: dict[str, float] = {
    "whisper-1": 0.006 / 60.0,
}


class WhisperTerminalError(Exception):
    """4xx or schema-parse failure. Do not retry. Caller should skip refinement."""


class WhisperRetryableError(Exception):
    """429/5xx after retries exhausted. Caller should skip refinement."""


def _classify_error(err: Exception) -> str:
    """Return ``'retryable'`` | ``'terminal'``. Mirrors LLM client logic."""
    try:
        import openai  # type: ignore

        retryable_types = tuple(
            t
            for t in (
                getattr(openai, "RateLimitError", None),
                getattr(openai, "APIConnectionError", None),
                getattr(openai, "APITimeoutError", None),
                getattr(openai, "InternalServerError", None),
            )
            if isinstance(t, type)
        )
        terminal_types = tuple(
            t
            for t in (
                getattr(openai, "BadRequestError", None),
                getattr(openai, "AuthenticationError", None),
                getattr(openai, "PermissionDeniedError", None),
                getattr(openai, "NotFoundError", None),
                getattr(openai, "UnprocessableEntityError", None),
            )
            if isinstance(t, type)
        )
        if retryable_types and isinstance(err, retryable_types):
            return "retryable"
        if terminal_types and isinstance(err, terminal_types):
            return "terminal"
    except ImportError:
        pass

    status = getattr(err, "status_code", None)
    if isinstance(status, int):
        if status == 429 or 500 <= status < 600:
            return "retryable"
        if 400 <= status < 500:
            return "terminal"

    if isinstance(err, asyncio.TimeoutError):
        return "terminal"

    return "retryable"


def _estimated_cost_usd(model: str, duration_seconds: float) -> float:
    """Estimate or finalize cost for a transcription.

    Used twice:
    - Pre-call with caller's duration estimate (for budget reservation).
    - Post-call with API-reported duration (for spend record).
    """
    rate = _WHISPER_USD_PER_SECOND.get(model)
    if rate is None:
        # Unknown model — fall back to whisper-1 rate to avoid free
        # transcription if a future model isn't priced yet.
        rate = _WHISPER_USD_PER_SECOND["whisper-1"]
    return max(0.0, duration_seconds) * rate


def _parse_words(response: Any) -> tuple[WhisperWord, ...]:
    """Extract word list from a ``verbose_json`` Whisper response.

    The OpenAI SDK returns either a ``Transcription`` Pydantic model
    or a dict (depending on version). Tolerate both.
    """
    raw_words = None
    if hasattr(response, "words"):
        raw_words = response.words
    elif isinstance(response, dict):
        raw_words = response.get("words")
    if not raw_words:
        return ()

    out: list[WhisperWord] = []
    for w in raw_words:
        if hasattr(w, "word"):
            text = getattr(w, "word", "")
            start = getattr(w, "start", 0.0)
            end = getattr(w, "end", 0.0)
        elif isinstance(w, dict):
            text = w.get("word", "")
            start = w.get("start", 0.0)
            end = w.get("end", 0.0)
        else:
            continue
        try:
            text_str = str(text).strip()
            start_ms = int(round(float(start) * 1000))
            end_ms = int(round(float(end) * 1000))
        except (TypeError, ValueError):
            continue
        if not text_str:
            continue
        # Whisper occasionally emits end < start for very short words;
        # clamp rather than raise so one bad word doesn't kill the
        # whole transcript.
        if end_ms < start_ms:
            end_ms = start_ms
        out.append(WhisperWord(word=text_str, start_ms=start_ms, end_ms=end_ms))
    return tuple(out)


def _extract_field(response: Any, name: str, default: Any) -> Any:
    if hasattr(response, name):
        return getattr(response, name, default)
    if isinstance(response, dict):
        return response.get(name, default)
    return default


class WhisperTranscriber:
    """Async Whisper wrapper. One instance per api process.

    Construction is cheap; the underlying ``AsyncOpenAI`` lazy-validates
    the api_key on first use, so tests can pass ``api_key="test"`` and
    monkeypatch ``self._client`` with a mock.
    """

    def __init__(
        self,
        *,
        api_key: str,
        budget_tracker: BudgetTracker,
        model: str = "whisper-1",
        timeout_s: float = 60.0,
        max_retries: int = 3,
        backoff_base_s: float = 0.5,
        backoff_max_s: float = 8.0,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAI API key is required")
        if model not in _WHISPER_USD_PER_SECOND:
            logger.warning(
                "whisper_unknown_model_pricing_fallback",
                extra={"model": model, "fallback_rate": "whisper-1"},
            )
        try:
            from openai import AsyncOpenAI
        except ImportError as e:
            raise RuntimeError(
                "openai SDK not installed — add `openai>=1.40` to "
                "services/api/pyproject.toml"
            ) from e

        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout_s)
        self._model = model
        self._timeout_s = timeout_s
        self._budget = budget_tracker
        self._max_retries = max_retries
        self._backoff_base_s = backoff_base_s
        self._backoff_max_s = backoff_max_s

    @property
    def model(self) -> str:
        return self._model

    async def transcribe(
        self,
        *,
        audio_bytes: bytes,
        audio_duration_seconds: float,
        filename: str = "audio.mp4",
        language: str = "ko",
        prompt: str | None = None,
    ) -> WhisperResult:
        """Transcribe audio bytes to word-timed text.

        Args:
            audio_bytes: Raw audio file contents. MP4/MP3/WAV/M4A all
                accepted by Whisper. Caller is responsible for keeping
                this under 25 MB (Whisper's hard upload limit).
            audio_duration_seconds: Estimated duration. Used pre-call
                for budget reservation; the API-reported duration
                supersedes this for the actual spend record.
            filename: Filename hint passed to OpenAI's multipart upload.
                Affects content-type sniffing. Default ``"audio.mp4"``.
            language: ISO 639-1 code. Pin this for known-language
                tenants — improves accuracy and reduces hallucination.
            prompt: Optional bias text (e.g. product names). Whisper
                uses this to prefer specific spellings. Hard limit is
                224 tokens on OpenAI's side; we don't enforce that
                here, the API will reject overlong prompts.

        Returns:
            :class:`WhisperResult`.

        Raises:
            BudgetExceededError: Daily ceiling hit before this call.
            WhisperTerminalError: 4xx (auth, validation, file-too-big).
                Do not retry.
            WhisperRetryableError: 429/5xx after retries exhausted.
        """
        if not audio_bytes:
            raise ValueError("audio_bytes must be non-empty")

        estimated_cost = _estimated_cost_usd(self._model, audio_duration_seconds)
        self._budget.check_and_reserve(estimated_cost)

        attempt = 0
        start = time.monotonic()
        last_err: Exception | None = None
        response: Any = None

        try:
            while attempt <= self._max_retries:
                attempt += 1
                # Each retry uses a fresh BytesIO — the SDK consumes
                # the stream on send, so a reused buffer would upload
                # zero bytes on retry.
                buf = io.BytesIO(audio_bytes)
                buf.name = filename  # type: ignore[attr-defined]

                kwargs: dict[str, Any] = {
                    "model": self._model,
                    "file": buf,
                    "response_format": "verbose_json",
                    "timestamp_granularities": ["word"],
                    "language": language,
                }
                if prompt:
                    kwargs["prompt"] = prompt

                try:
                    response = await asyncio.wait_for(
                        self._client.audio.transcriptions.create(**kwargs),
                        timeout=self._timeout_s,
                    )
                    break
                except Exception as e:  # noqa: BLE001
                    classification = _classify_error(e)
                    last_err = e
                    if classification == "retryable" and attempt <= self._max_retries:
                        sleep_s = min(
                            self._backoff_max_s,
                            self._backoff_base_s * (2 ** (attempt - 1)),
                        )
                        logger.warning(
                            "whisper_retry",
                            extra={
                                "attempt": attempt,
                                "max_retries": self._max_retries,
                                "sleep_s": sleep_s,
                                "error_type": type(e).__name__,
                                "error": str(e)[:500],
                            },
                        )
                        await asyncio.sleep(sleep_s)
                        continue
                    if classification == "terminal":
                        self._budget.release_reservation(estimated_cost)
                        raise WhisperTerminalError(
                            f"{type(e).__name__}: {e}"
                        ) from e
                    break

            if response is None:
                self._budget.release_reservation(estimated_cost)
                raise WhisperRetryableError(
                    f"whisper call failed after {self._max_retries} retries: "
                    f"{type(last_err).__name__ if last_err else 'Unknown'}: {last_err}"
                ) from last_err
        except (WhisperTerminalError, WhisperRetryableError):
            raise
        except Exception:
            self._budget.release_reservation(estimated_cost)
            raise

        latency_ms = int((time.monotonic() - start) * 1000)
        words = _parse_words(response)
        text = str(_extract_field(response, "text", ""))
        detected_language = str(_extract_field(response, "language", language))
        api_duration = float(
            _extract_field(response, "duration", audio_duration_seconds)
        )
        actual_cost = _estimated_cost_usd(self._model, api_duration)
        self._budget.record(actual_cost)

        return WhisperResult(
            words=words,
            text=text,
            language=detected_language,
            duration_seconds=api_duration,
            cost_usd=actual_cost,
            latency_ms=latency_ms,
        )
