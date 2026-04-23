"""Async OpenAI client for the shorts-auto LLM scene picker.

Endpoint is user-facing, so this client is ASYNC (unlike image_caption's
sync+threading pattern which lives inside a worker). Uses ``AsyncOpenAI``
and wraps it with:

- per-call hard timeout (asyncio.wait_for)
- bounded retries on 429 / 5xx / network (exponential backoff)
- pre-call daily budget guard + post-call spend record
- forced ``response_format=json_schema`` for structured output
- seed + temperature=0 for deterministic picks

Error contract:
- ``LLMTerminalError``: 4xx (auth/validation) — do NOT retry, do NOT
  fall through to another attempt. Caller should fallback.
- ``LLMRetryableError``: 429/5xx after retries exhausted. Caller should
  fallback.
- ``BudgetExceededError`` (from ``.budget``): daily cap hit. Caller
  should fallback.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from .budget import BudgetTracker

logger = logging.getLogger(__name__)


# Pricing snapshot as of 2026-04. Mirrors image_caption/openai_client.py.
# Values are USD per 1M tokens.
MODEL_PRICING_USD_PER_MTOK: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 2.50, "cached_input": 1.25, "output": 10.00},
    "gpt-4o-2024-11-20": {"input": 2.50, "cached_input": 1.25, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "cached_input": 0.075, "output": 0.60},
}


class LLMTerminalError(Exception):
    """4xx or schema-parse failure. Do not retry. Fall back to pure."""


class LLMRetryableError(Exception):
    """429/5xx after retries exhausted. Fall back to pure."""


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_prompt_tokens: int = 0


@dataclass
class LLMCallResult:
    text: str  # raw JSON string
    usage: TokenUsage
    model: str
    cost_usd: float
    latency_ms: int


def _estimate_cost_usd(model: str, usage: TokenUsage) -> float:
    pricing = MODEL_PRICING_USD_PER_MTOK.get(model)
    if pricing is None:
        pricing = MODEL_PRICING_USD_PER_MTOK["gpt-4o"]
    cached = usage.cached_prompt_tokens
    non_cached = max(0, usage.prompt_tokens - cached)
    return (
        non_cached * pricing["input"] / 1_000_000
        + cached * pricing["cached_input"] / 1_000_000
        + usage.completion_tokens * pricing["output"] / 1_000_000
    )


def _extract_usage(response: Any) -> TokenUsage:
    raw = getattr(response, "usage", None)
    if raw is None:
        return TokenUsage()

    def _g(obj: Any, name: str, default: int = 0) -> int:
        val = getattr(obj, name, None)
        if val is None and isinstance(obj, dict):
            val = obj.get(name)
        if val is None:
            return default
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    prompt = _g(raw, "prompt_tokens")
    completion = _g(raw, "completion_tokens")
    total = _g(raw, "total_tokens") or (prompt + completion)
    cached = 0
    details = getattr(raw, "prompt_tokens_details", None)
    if details is not None:
        cached = _g(details, "cached_tokens")
    return TokenUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        cached_prompt_tokens=cached,
    )


def _classify_error(err: Exception) -> str:
    """Return 'retryable' | 'terminal'."""
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

    # Asyncio timeout on the wait_for wrapper is terminal for this
    # request (caller falls back); OpenAI-side timeout is retryable.
    if isinstance(err, asyncio.TimeoutError):
        return "terminal"

    return "retryable"


class OpenAIClipClient:
    """Async chat-completions wrapper for the LLM scorer.

    One instance per api process. The service calls ``await call(...)``
    with pre-built messages + json_schema; this class owns nothing about
    the prompt content.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_s: float,
        budget_tracker: BudgetTracker,
        max_retries: int = 3,
        backoff_base_s: float = 0.5,
        backoff_max_s: float = 8.0,
        estimated_cost_per_call_usd: float = 0.003,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAI API key is required")
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
        self._estimated_cost_per_call_usd = estimated_cost_per_call_usd

    @property
    def model(self) -> str:
        return self._model

    async def call(
        self,
        *,
        messages: list[dict[str, Any]],
        response_format: dict[str, Any],
        seed: int | None = 42,
    ) -> LLMCallResult:
        """Execute one chat completion. Raises on terminal / exhausted-retry
        errors; caller handles fallback.
        """
        self._budget.check_and_reserve(self._estimated_cost_per_call_usd)

        attempt = 0
        start = time.monotonic()
        last_err: Exception | None = None
        response: Any = None

        while attempt <= self._max_retries:
            attempt += 1
            try:
                response = await asyncio.wait_for(
                    self._client.chat.completions.create(
                        model=self._model,
                        messages=messages,  # type: ignore[arg-type]
                        response_format={
                            "type": "json_schema",
                            "json_schema": response_format,
                        },
                        temperature=0,
                        seed=seed,
                    ),
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
                        "shorts_auto_llm_retry",
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
                    raise LLMTerminalError(f"{type(e).__name__}: {e}") from e
                # retries exhausted on a retryable error
                break

        if response is None:
            raise LLMRetryableError(
                f"openai call failed after {self._max_retries} retries: "
                f"{type(last_err).__name__ if last_err else 'Unknown'}: {last_err}"
            ) from last_err

        latency_ms = int((time.monotonic() - start) * 1000)
        choice = response.choices[0]
        text = choice.message.content or ""
        usage = _extract_usage(response)
        cost_usd = _estimate_cost_usd(self._model, usage)
        self._budget.record(cost_usd)
        return LLMCallResult(
            text=text,
            usage=usage,
            model=self._model,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
        )
