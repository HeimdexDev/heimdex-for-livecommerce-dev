"""Caption engines for image captioning.

Pure library — zero imports from anything in app/. The only consumer is
app.modules.image_caption.service. Keeping this package self-contained
means we can extract it into a dedicated worker later without rewriting.

Public surface:
  - CaptionEngine (Protocol)
  - CaptionResult, TokenUsage
  - BudgetExceededError, PersonSafetyViolation, RetryableEngineError,
    TerminalEngineError
  - build_image_caption_engine(settings) — factory
"""

from .base import (
    BudgetExceededError,
    CaptionEngine,
    CaptionResult,
    EngineError,
    PersonSafetyViolation,
    RetryableEngineError,
    TerminalEngineError,
    TokenUsage,
)
from .factory import build_image_caption_engine

__all__ = [
    "BudgetExceededError",
    "CaptionEngine",
    "CaptionResult",
    "EngineError",
    "PersonSafetyViolation",
    "RetryableEngineError",
    "TerminalEngineError",
    "TokenUsage",
    "build_image_caption_engine",
]
