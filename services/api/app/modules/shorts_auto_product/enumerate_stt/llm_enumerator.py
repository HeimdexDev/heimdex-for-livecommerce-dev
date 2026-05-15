"""gpt-4o-mini transcript enumeration with strict-JSON output.

One-shot call: feed the serialized transcript blob into the LLM,
get back a list of products the host actively sells. Output is
re-validated through :class:`TranscriptEnumerationResponse` so a
hallucinated payload can't poison the catalog.

Quote-fidelity post-check (defense against hallucinated example
quotes): every emitted ``example_quote`` must appear as a substring
of the source transcript. Whitespace normalized before comparison
because the LLM occasionally collapses inner whitespace. Products
that fail are dropped from the response with a logged warning;
remaining products pass through.

Loose-coupling: imports ONLY ``openai`` (already a top-level api
dependency), :mod:`heimdex_media_contracts.product`, and own-module
symbols. No cross-imports from other ``app.modules.*``.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from heimdex_media_contracts.product import (
    TRANSCRIPT_ENUMERATION_PROMPT_VERSION,
    TranscriptEnumerationPrompt,
    TranscriptEnumerationResponse,
)
from pydantic import ValidationError

from app.modules.shorts_auto_product.enumerate_stt.errors import (
    EnumerationLLMError,
)

logger = logging.getLogger(__name__)


_DEFAULT_MODEL = "gpt-4o-mini"
# 90s caps the absolute wall time. Transcripts up to ~80k tokens
# ingest in ~10-30s; the 90s ceiling is forgiving for the worst
# case while keeping the wizard's 180s polling timeout in reach.
_DEFAULT_TIMEOUT_S = 90.0
# Cap on response tokens. The LLM emits a small JSON payload (~50
# products max × ~200 tokens each = 10k); 4096 leaves headroom.
_DEFAULT_MAX_OUTPUT_TOKENS = 4096

# Cost-per-million tokens (USD) for gpt-4o-mini. These are the
# pricing-page numbers as of 2026-04. They drive the post-call
# cost estimate surfaced to the budget tracker; if pricing drifts,
# the goldens-eval cost numbers will look wrong but the gating
# logic stays correct (the budget cap is itself env-tunable).
_GPT_4O_MINI_INPUT_USD_PER_M = 0.15
_GPT_4O_MINI_OUTPUT_USD_PER_M = 0.60


# Hand-rolled JSON schema for OpenAI's structured-output mode —
# same rationale as ``aliases.generator._RESPONSE_JSON_SCHEMA``:
# OpenAI's strict mode wants ``additionalProperties: false`` and
# Pydantic's ``model_json_schema()`` doesn't always emit it. Re-
# validation through the contracts model catches drift.
_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "name": "transcript_enumeration_response",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["products", "prompt_version", "model"],
        "properties": {
            "products": {
                "type": "array",
                "maxItems": 50,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "llm_label",
                        "spoken_aliases",
                        "first_mention_ms",
                        "example_quote",
                        "confidence",
                    ],
                    "properties": {
                        "llm_label": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 200,
                        },
                        "spoken_aliases": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": 10,
                        },
                        "first_mention_ms": {
                            "type": "integer",
                            "minimum": 0,
                        },
                        "example_quote": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 500,
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                        },
                    },
                },
            },
            "prompt_version": {"type": "string", "minLength": 1},
            "model": {"type": "string", "minLength": 1},
        },
    },
}


@dataclass(frozen=True)
class TranscriptEnumerationResult:
    """Pure-data result. Caller persists via the catalog repository.

    ``products`` is the post-fidelity-check survivors — products
    whose ``example_quote`` was NOT found in the source transcript
    are silently dropped (with a logged warning). ``dropped_count``
    surfaces the drop count for observability without leaking
    drift-prone product data into log lines.
    """

    products: list[Any]  # list[TranscriptEnumeratedProduct]
    cost_usd: float
    latency_ms: int
    prompt_version: str
    model: str
    dropped_count: int


class TranscriptEnumerator:
    """One-shot transcript enumerator.

    Construct once per app process so the underlying ``AsyncOpenAI``
    connection pool is reused across requests.
    """

    def __init__(
        self,
        *,
        openai_client: Any,
        model: str = _DEFAULT_MODEL,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        max_output_tokens: int = _DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> None:
        self._openai = openai_client
        self._model = model
        self._timeout_s = timeout_s
        self._max_output_tokens = max_output_tokens

    @property
    def model(self) -> str:
        return self._model

    @property
    def prompt_version(self) -> str:
        return TRANSCRIPT_ENUMERATION_PROMPT_VERSION

    async def enumerate(
        self,
        *,
        transcript: str,
    ) -> TranscriptEnumerationResult:
        """Run the LLM call + quote-fidelity post-check.

        Args:
            transcript: The serialized
                ``[mm:ss] {text}`` newline-joined string from
                :func:`transcript_loader.load_transcript`. Quote
                fidelity is checked against this exact string.

        Raises:
            :class:`EnumerationLLMError`: timeout, schema mismatch,
                OpenAI-side error, JSON parse failure.
        """
        if not transcript.strip():
            # Defensive — caller should have raised
            # TranscriptUnavailableError before getting here.
            raise EnumerationLLMError(
                "transcript is empty; nothing to enumerate"
            )

        messages = self._build_messages(transcript=transcript)

        start = time.monotonic()
        try:
            response = await self._openai.chat.completions.create(
                model=self._model,
                messages=messages,
                response_format={
                    "type": "json_schema",
                    "json_schema": _RESPONSE_JSON_SCHEMA,
                },
                timeout=self._timeout_s,
                max_tokens=self._max_output_tokens,
            )
        except Exception as e:  # noqa: BLE001 — wrap-and-rethrow
            latency_ms = int((time.monotonic() - start) * 1000)
            logger.warning(
                "stt_enum_llm_call_failed",
                extra={
                    "model": self._model,
                    "latency_ms": latency_ms,
                    "error": str(e)[:300],
                },
            )
            raise EnumerationLLMError(
                f"OpenAI call failed: {e}",
            ) from e

        latency_ms = int((time.monotonic() - start) * 1000)
        usage = getattr(response, "usage", None)
        cost_usd = _estimate_cost_usd(usage, self._model)

        # Parse the JSON payload + revalidate through the pydantic
        # model. ``json.loads`` here surfaces a clear error if the
        # response wasn't valid JSON; ``model_validate`` catches
        # any field-level invariant the schema missed.
        choice = response.choices[0]
        raw_content = choice.message.content
        try:
            payload = json.loads(raw_content)
            # Force the model + prompt_version to whatever the LLM
            # actually used; the schema requires them in the response
            # but the LLM occasionally guesses model identifiers
            # ("gpt-4" without the suffix), and we want the truth.
            payload["model"] = self._model
            payload["prompt_version"] = self.prompt_version
            parsed = TranscriptEnumerationResponse.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning(
                "stt_enum_llm_schema_mismatch",
                extra={
                    "model": self._model,
                    "error": str(e)[:300],
                    "raw_preview": (raw_content or "")[:200],
                },
            )
            raise EnumerationLLMError(
                f"LLM response failed schema validation: {e}",
            ) from e

        # Quote-fidelity post-check. The LLM occasionally emits an
        # ``example_quote`` that paraphrases rather than quotes; the
        # downstream UX (provenance tooltip) breaks if those slip
        # through, and they're a leading indicator of low-quality
        # extraction overall.
        #
        # Strip the ``[mm:ss]`` markers from the haystack — those are
        # ours, not the host's — so a quote that spans a scene
        # boundary still matches. The LLM is told the markers are
        # timestamps; it does NOT include them in example_quote.
        # Use NFKC + punctuation-strip on BOTH sides — the LLM and the
        # STT pass disagree on punctuation cadence often enough that a
        # whitespace-only normalize was rejecting real verbatim quotes.
        normalized_transcript = _normalize_for_fidelity(
            _strip_timestamp_markers(transcript)
        )
        kept: list[Any] = []
        dropped = 0
        dropped_samples: list[str] = []
        for product in parsed.products:
            normalized_quote = _normalize_for_fidelity(product.example_quote)
            if normalized_quote and normalized_quote in normalized_transcript:
                kept.append(product)
            else:
                dropped += 1
                # Capture a small sample of dropped quotes for the
                # warning log so calibration goldens (PR 5) can be
                # tuned against real misses without re-running the LLM.
                if len(dropped_samples) < 3:
                    dropped_samples.append(product.example_quote[:80])

        if dropped:
            logger.warning(
                "stt_enum_quote_fidelity_drops",
                extra={
                    "dropped_count": dropped,
                    "kept_count": len(kept),
                    "model": self._model,
                    "dropped_quote_samples": dropped_samples,
                },
            )

        return TranscriptEnumerationResult(
            products=kept,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            prompt_version=self.prompt_version,
            model=self._model,
            dropped_count=dropped,
        )

    def _build_messages(self, *, transcript: str) -> list[dict[str, Any]]:
        return [
            {
                "role": "system",
                "content": TranscriptEnumerationPrompt.SYSTEM,
            },
            {
                "role": "user",
                "content": TranscriptEnumerationPrompt.USER_TEMPLATE.format(
                    transcript=transcript,
                ),
            },
        ]


# ---------- pure helpers ----------


_WHITESPACE_RE = re.compile(r"\s+")
# ``[mm:ss]`` or ``[m:ss]`` marker, with arbitrary digit length on the
# minutes side (long videos render as ``[127:33]``).
_TIMESTAMP_MARKER_RE = re.compile(r"\[\d+:\d{2}\]")
# Punctuation + Korean / fullwidth quote marks the LLM can emit at
# different cadence than the source transcript. The fidelity check
# strips these on BOTH sides so a paraphrase still gets caught while
# punctuation drift does not falsely reject a real quote.
_PUNCTUATION_RE = re.compile(
    r"[.,?!~・「」『』\"\'()\[\]<>:;…—\-—~"
    r"“”‘’、。．，？！]"
)


def _strip_timestamp_markers(text: str) -> str:
    """Remove the ``[mm:ss]`` line markers we injected.

    The LLM is instructed to read these as timestamps (NOT to include
    them in ``example_quote``). When checking quote fidelity we don't
    want the markers to break a contiguous match across what was a
    scene boundary in the transcript. Pure function — testable in
    isolation.
    """
    return _TIMESTAMP_MARKER_RE.sub(" ", text)


def _normalize_for_fidelity(text: str) -> str:
    """Aggressive normalization for the quote-fidelity substring check.

    Real-world Korean transcripts vs LLM-emitted quotes diverge on:

    * Punctuation cadence — the STT pass adds period/comma where the
      host paused; the LLM-quoted version may drop those, or add a
      Korean comma where there wasn't one.
    * Unicode normalization — Hangul syllables can be NFC composed
      (``하``) or NFD decomposed (``ㅎ + ㅏ``); Latin/digit characters
      can be fullwidth (``１``) vs halfwidth (``1``). NFKC collapses
      both into a single canonical form so a fullwidth digit in one
      side matches a halfwidth in the other.
    * Whitespace cadence — already handled (run-collapse + strip).

    We keep this conservative on the linguistic axis: do NOT casefold
    Korean (no-op anyway) and do NOT strip Korean particles. The goal
    is to catch a true paraphrase (different words / clauses) while
    tolerating punctuation drift.
    """
    import unicodedata

    nfkc = unicodedata.normalize("NFKC", text)
    no_punct = _PUNCTUATION_RE.sub("", nfkc)
    return _WHITESPACE_RE.sub(" ", no_punct).strip()


# Backward-compat alias — older callers in this module use the old
# name. _normalize_for_fidelity is the new canonical entry point.
def _normalize_whitespace(text: str) -> str:
    """Deprecated alias retained for callers that only need
    whitespace-collapse semantics. New call sites should use
    :func:`_normalize_for_fidelity` which adds NFKC + punctuation-strip.
    """
    return _WHITESPACE_RE.sub(" ", text).strip()


def _estimate_cost_usd(usage: Any, model: str) -> float:
    """Cost estimate from ``response.usage`` token counts.

    Returns 0.0 when the SDK doesn't surface usage (e.g., a mock in
    tests). Only known models get a non-zero estimate; unknown
    models return 0.0 with a debug log so the budget tracker still
    sums cleanly.
    """
    if usage is None:
        return 0.0
    if not model.startswith("gpt-4o-mini"):
        logger.debug(
            "stt_enum_cost_unknown_model",
            extra={"model": model},
        )
        return 0.0
    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    return (
        (prompt_tokens / 1_000_000) * _GPT_4O_MINI_INPUT_USD_PER_M
        + (completion_tokens / 1_000_000) * _GPT_4O_MINI_OUTPUT_USD_PER_M
    )
