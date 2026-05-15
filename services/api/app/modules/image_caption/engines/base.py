"""CaptionEngine Protocol and result types.

Pure types. No runtime dependency on openai, torch, or any model library so
this module can be imported by tests, the factory, and alternate engines
without dragging in heavy deps.

Contract (worker → engine):
    result = engine.caption(image_path, hints={"org_id": ..., "file_name": ...})
    if result.caption:
        post_enrich(scene_id, result.caption)

Engines MUST raise EngineError subclasses for anything the worker should
retry (RetryableEngineError) or surface as a terminal failure
(TerminalEngineError). BudgetExceededError and PersonSafetyViolation are
both terminal from the scene's perspective — BudgetExceededError is also
process-wide actionable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_prompt_tokens: int = 0


@dataclass(frozen=True)
class CaptionResult:
    """Engine output for a single image.

    caption is the only field the existing ingest path reads today. The rest
    are additive — logs, metrics, and phase-3 structured fields persistence
    can pick them up without the engine contract changing.
    """

    caption: str
    prompt_version: str
    model: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    structured: dict[str, Any] | None = None
    latency_ms: int = 0
    validation_failure: str | None = None


class EngineError(Exception):
    """Base class for all caption engine errors."""


class RetryableEngineError(EngineError):
    """Transient failure. Worker should let SQS redeliver the message."""


class TerminalEngineError(EngineError):
    """Permanent failure for this input. Do not retry."""


class BudgetExceededError(EngineError):
    """Daily cost budget exhausted. Process-wide circuit breaker.

    Treated as retryable so SQS redelivers after the budget window resets
    (next day). Worker should also log prominently and alert.
    """


class PersonSafetyViolation(TerminalEngineError):
    """Caption leaked banned person-identifying terms.

    Non-retryable: retrying with the same prompt + same image will produce
    the same violation. Scene is marked failed; manual review required.
    """


@runtime_checkable
class CaptionEngine(Protocol):
    """All caption engines conform to this surface.

    Implementations:
      - Qwen2VLEngine   (wraps heimdex_media_pipelines.vision)
      - OpenAIEngine    (gpt-4o via hosted API)
      - <future>        Gemini, Claude, etc.
    """

    name: str

    def caption(
        self,
        image_path: Path | str,
        hints: dict[str, Any] | None = None,
    ) -> CaptionResult: ...

    def close(self) -> None: ...
