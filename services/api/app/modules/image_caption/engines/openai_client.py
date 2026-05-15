"""Thin chokepoint around the OpenAI Chat Completions API.

All OpenAI calls for captioning go through OpenAICaptionClient.call().
This is the single place we:
  - load the API key
  - enforce concurrency
  - enforce per-call timeout
  - retry on 429 / 5xx / transient network errors
  - track daily cost against a budget
  - extract token usage + compute cost

Design notes
------------
Sync, not async — the drive-caption-worker is thread-based. The OpenAI
SDK is blocking; we wrap it with threading.Semaphore for concurrency
and threading.Lock for the budget counter.

Budget tracking is pluggable via the BudgetTracker protocol. Default is
InMemoryBudgetTracker, which is correct for a single-replica worker and
keeps phase 1 free of a Redis dependency. RedisBudgetTracker can be
added later without touching callers.

Prompt caching: messages are always laid out as
    [system_msg, *few_shot_turns, user_image_msg]
The first N messages are identical across calls so OpenAI's automatic
prompt caching kicks in. Only the user_image_msg varies per image.

Cost table is a hard-coded fallback. Real spend is the authoritative
source; this exists only for the circuit breaker pre-check.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol

from .base import (
    BudgetExceededError,
    RetryableEngineError,
    TerminalEngineError,
    TokenUsage,
)

logger = logging.getLogger(__name__)


# Pricing snapshot as of 2026-04. Update when OpenAI publishes new prices.
# Values are USD per 1M tokens. Used for the pre-call budget guard and
# post-call spend tracking. If OpenAI's published prices drift past these,
# the integration test test_openai_engine_cost_estimate will fail.
MODEL_PRICING_USD_PER_MTOK: dict[str, dict[str, float]] = {
    "gpt-4o": {
        "input": 2.50,
        "cached_input": 1.25,
        "output": 10.00,
    },
    "gpt-4o-2024-11-20": {
        "input": 2.50,
        "cached_input": 1.25,
        "output": 10.00,
    },
    "gpt-4o-mini": {
        "input": 0.15,
        "cached_input": 0.075,
        "output": 0.60,
    },
}


def _estimate_cost_usd(model: str, usage: TokenUsage) -> float:
    pricing = MODEL_PRICING_USD_PER_MTOK.get(model)
    if pricing is None:
        # Fall back to gpt-4o pricing — safer to over-estimate than under.
        pricing = MODEL_PRICING_USD_PER_MTOK["gpt-4o"]
    cached = usage.cached_prompt_tokens
    non_cached_prompt = max(0, usage.prompt_tokens - cached)
    return (
        non_cached_prompt * pricing["input"] / 1_000_000
        + cached * pricing["cached_input"] / 1_000_000
        + usage.completion_tokens * pricing["output"] / 1_000_000
    )


def _today_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


class BudgetTracker(Protocol):
    def check_and_reserve(self, estimated_cost_usd: float) -> None: ...
    def record(self, actual_cost_usd: float) -> None: ...
    def spent_today_usd(self) -> float: ...


@dataclass
class InMemoryBudgetTracker:
    daily_budget_usd: float
    _lock: threading.Lock = None  # type: ignore[assignment]
    _date: str = ""
    _spent_usd: float = 0.0
    _reserved_usd: float = 0.0

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self._date = _today_utc()

    def _roll_day_if_needed(self) -> None:
        today = _today_utc()
        if today != self._date:
            self._date = today
            self._spent_usd = 0.0
            self._reserved_usd = 0.0

    def check_and_reserve(self, estimated_cost_usd: float) -> None:
        with self._lock:
            self._roll_day_if_needed()
            projected = self._spent_usd + self._reserved_usd + estimated_cost_usd
            if projected > self.daily_budget_usd:
                raise BudgetExceededError(
                    f"daily budget exceeded: "
                    f"spent=${self._spent_usd:.4f} "
                    f"reserved=${self._reserved_usd:.4f} "
                    f"estimated_next=${estimated_cost_usd:.4f} "
                    f"limit=${self.daily_budget_usd:.2f}"
                )
            self._reserved_usd += estimated_cost_usd

    def record(self, actual_cost_usd: float) -> None:
        with self._lock:
            self._roll_day_if_needed()
            # Release the reservation (approximately) and add actual.
            # Drift over many calls is bounded because we roll daily.
            self._reserved_usd = max(0.0, self._reserved_usd - actual_cost_usd)
            self._spent_usd += actual_cost_usd

    def spent_today_usd(self) -> float:
        with self._lock:
            self._roll_day_if_needed()
            return self._spent_usd


@dataclass
class OpenAICallResult:
    text: str
    usage: TokenUsage
    model: str
    cost_usd: float
    latency_ms: int


class OpenAICaptionClient:
    """Blocking OpenAI wrapper. One instance per worker process.

    Callers pass pre-built messages; this class owns nothing about the
    prompt content. Prompt assembly lives in openai_engine.py.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_s: float,
        max_concurrency: int,
        budget_tracker: BudgetTracker,
        max_retries: int = 5,
        backoff_base_s: float = 1.0,
        backoff_max_s: float = 30.0,
        estimated_cost_per_call_usd: float = 0.012,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAI API key is required")
        try:
            import openai  # noqa: F401  (imported lazily below to keep tests light)
        except ImportError as e:
            raise RuntimeError(
                "openai SDK not installed — add `openai>=1.40` to "
                "drive-caption-worker/pyproject.toml"
            ) from e

        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, timeout=timeout_s)
        self._model = model
        self._timeout_s = timeout_s
        self._semaphore = threading.Semaphore(max_concurrency)
        self._budget = budget_tracker
        self._max_retries = max_retries
        self._backoff_base_s = backoff_base_s
        self._backoff_max_s = backoff_max_s
        self._estimated_cost_per_call_usd = estimated_cost_per_call_usd

    @property
    def model(self) -> str:
        return self._model

    def close(self) -> None:
        # openai.OpenAI has no public close; nothing to do. Kept for symmetry.
        pass

    def call(
        self,
        *,
        messages: list[dict[str, Any]],
        response_format: dict[str, Any],
        seed: int | None = 42,
    ) -> OpenAICallResult:
        """Execute one chat completion with retries and budget guard.

        Raises:
            BudgetExceededError: daily budget exhausted (retryable by SQS).
            RetryableEngineError: network/5xx after max_retries (retryable).
            TerminalEngineError: 400-class or parse failure (not retryable).
        """

        self._budget.check_and_reserve(self._estimated_cost_per_call_usd)

        attempt = 0
        start = time.monotonic()
        last_err: Exception | None = None

        while attempt <= self._max_retries:
            attempt += 1
            with self._semaphore:
                try:
                    response = self._client.chat.completions.create(
                        model=self._model,
                        messages=messages,  # type: ignore[arg-type]
                        response_format={
                            "type": "json_schema",
                            "json_schema": response_format,
                        },
                        temperature=0,
                        seed=seed,
                        timeout=self._timeout_s,
                    )
                except Exception as e:  # noqa: BLE001 — classify below
                    classification = _classify_error(e)
                    last_err = e
                    if classification == "retryable" and attempt <= self._max_retries:
                        sleep_s = min(
                            self._backoff_max_s,
                            self._backoff_base_s * (2 ** (attempt - 1)),
                        )
                        logger.warning(
                            "openai_caption_retry",
                            extra={
                                "attempt": attempt,
                                "max_retries": self._max_retries,
                                "sleep_s": sleep_s,
                                "error_type": type(e).__name__,
                                "error": str(e)[:500],
                            },
                        )
                        time.sleep(sleep_s)
                        continue
                    if classification == "terminal":
                        raise TerminalEngineError(
                            f"{type(e).__name__}: {e}"
                        ) from e
                    # Retries exhausted
                    break
                else:
                    # Success path
                    break

        if last_err is not None and attempt > self._max_retries:
            raise RetryableEngineError(
                f"openai call failed after {self._max_retries} retries: "
                f"{type(last_err).__name__}: {last_err}"
            ) from last_err

        latency_ms = int((time.monotonic() - start) * 1000)

        choice = response.choices[0]
        text = choice.message.content or ""

        usage = _extract_usage(response)
        cost_usd = _estimate_cost_usd(self._model, usage)
        self._budget.record(cost_usd)

        return OpenAICallResult(
            text=text,
            usage=usage,
            model=self._model,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
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
    """Return 'retryable' | 'terminal' | 'unknown'.

    Classification order:
      1. openai SDK exception types (if openai is importable)
      2. status_code attribute (works for fakes and real APIStatusError)
      3. Default: 'retryable' (SQS visibility bounds retries)
    """

    try:
        import openai  # type: ignore

        retryable_types = tuple(
            t for t in (
                getattr(openai, "RateLimitError", None),
                getattr(openai, "APIConnectionError", None),
                getattr(openai, "APITimeoutError", None),
                getattr(openai, "InternalServerError", None),
            ) if isinstance(t, type)
        )
        terminal_types = tuple(
            t for t in (
                getattr(openai, "BadRequestError", None),
                getattr(openai, "AuthenticationError", None),
                getattr(openai, "PermissionDeniedError", None),
                getattr(openai, "NotFoundError", None),
                getattr(openai, "UnprocessableEntityError", None),
            ) if isinstance(t, type)
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

    return "retryable"  # default to retry on unknown; SQS bounds it
