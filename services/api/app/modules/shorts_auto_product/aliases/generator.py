"""AliasGenerator — gpt-4o-mini per-entry spoken-form alias generation.

Async-first: this generator is called from the api process (CLI
backfill loop or a future fire-and-forget realtime hook), both of
which are already async. The OpenAI SDK's ``AsyncOpenAI`` client gives
us per-call timeout + native await without spinning up threads.

Cost model (gpt-4o-mini, low-detail vision):

* Input: ~600 system tokens + ~30 user-template tokens + 85 image
  tokens (low detail) ≈ 715 prompt tokens per call. At
  $0.15 / 1M input tokens that's $0.000107 per call.
* Output: max 200 tokens (typically <50). At $0.60 / 1M output
  tokens that's at most $0.00012.
* **Total: ~$0.0002 per catalog entry.** A 9-entry video is $0.002.
  The 50-entry org-wide ceiling is $0.01. Well below the
  ``auto_shorts_product_v2_daily_budget_usd=50.0`` cap.

The strict-JSON schema comes straight from the contracts library
(``AliasGenerationResponse``); we send it as the
``response_format=json_schema`` and re-validate the parsed JSON
through Pydantic so the LLM cannot hand us anything the schema
rejects.

No budget tracker is wired in v0.15.0 — the cost is small enough that
the existing ``product_scan_daily_costs`` ledger (used by the worker
heartbeats) is not adjusted by alias generation. If alias volume
ever grows past hundreds per day, attach a
``BudgetTracker`` here mirroring image_caption's pattern.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from heimdex_media_contracts.product import (
    ALIAS_GENERATION_PROMPT_VERSION,
    AliasGenerationPrompt,
    AliasGenerationResponse,
)
from pydantic import ValidationError

from app.modules.shorts_auto_product.aliases.errors import (
    AliasGenerationRetryable,
    AliasGenerationTerminal,
)

logger = logging.getLogger(__name__)


_DEFAULT_MODEL = "gpt-4o-mini"
_DEFAULT_TIMEOUT_S = 15.0
_DEFAULT_MAX_OUTPUT_TOKENS = 200
# Cap S3 image fetches. Canonical crops are <500 KB in practice; this
# defends against a misconfigured ``canonical_crop_s3_key`` that points
# at a multi-MB original frame.
_MAX_IMAGE_BYTES = 5 * 1024 * 1024

# Fallback for the contracts no-image template until the contracts
# release lands. CI/prod run against the PyPI-published contracts,
# which predates AliasGenerationPrompt.USER_TEMPLATE_NO_IMAGE; the
# getattr in _build_messages_text_only prefers the contracts copy
# once released. TODO: remove after the contracts release that
# ships USER_TEMPLATE_NO_IMAGE.
_FALLBACK_USER_TEMPLATE_NO_IMAGE = (
    "Generate spoken-form aliases for the following product. "
    "No reference image is available — infer from the label "
    "text alone.\n"
    "\n"
    "Product label (from vision LLM reading the packaging): {label}"
)


# JSON schema for OpenAI's structured-output mode. Hand-rolled (not
# auto-derived from AliasGenerationResponse) because OpenAI's strict
# mode requires ``additionalProperties: false`` which Pydantic's
# ``json_schema()`` doesn't always emit. Re-validation through the
# contracts model catches any drift between this schema and the
# Pydantic model.
_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "name": "alias_generation_response",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["aliases"],
        "properties": {
            "aliases": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 10,
                "description": (
                    "Spoken-form aliases (3-5 ideal). Each ≤30 chars, "
                    "substring-matchable, no sentences."
                ),
            }
        },
    },
}


@dataclass(frozen=True)
class AliasGenerationResult:
    """Pure-data result. Caller persists via the catalog repository.

    ``cost_usd`` is the post-call estimate; ``latency_ms`` is wall
    time. Both are surfaced to the CLI summary so a backfill operator
    can sanity-check spend against expectation.
    """

    aliases: list[str]
    cost_usd: float
    latency_ms: int
    prompt_version: str
    model: str


class AliasGenerator:
    """One-shot alias generator. Async, stateless per call.

    Construct once per CLI run (or per app process for the realtime
    hook) so the underlying ``AsyncOpenAI`` connection pool is reused
    across entries.
    """

    def __init__(
        self,
        *,
        openai_client: Any,
        s3_client: Any,
        model: str = _DEFAULT_MODEL,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        image_detail: str = "low",
        max_output_tokens: int = _DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> None:
        if image_detail not in ("low", "high", "auto"):
            raise ValueError(f"invalid image_detail: {image_detail!r}")
        self._openai = openai_client
        self._s3 = s3_client
        self._model = model
        self._timeout_s = timeout_s
        self._image_detail = image_detail
        self._max_output_tokens = max_output_tokens

    @property
    def model(self) -> str:
        return self._model

    @property
    def prompt_version(self) -> str:
        return ALIAS_GENERATION_PROMPT_VERSION

    async def generate(
        self,
        *,
        canonical_crop_s3_key: str | None,
        llm_label: str,
    ) -> AliasGenerationResult:
        """Generate aliases for one catalog entry.

        When ``canonical_crop_s3_key`` is falsy, runs in text-only
        mode (no S3 fetch, label-only prompt). Raises
        :class:`AliasGenerationTerminal` if the S3 image (when
        present) is missing/malformed, or if the LLM output cannot
        be coerced into :class:`AliasGenerationResponse`. Raises
        :class:`AliasGenerationRetryable` for transient OpenAI errors.
        """

        if canonical_crop_s3_key:
            image_bytes = self._download_crop(canonical_crop_s3_key)
            data_url = _to_data_url(image_bytes)
            messages = self._build_messages(
                data_url=data_url, label=llm_label,
            )
        else:
            messages = self._build_messages_text_only(label=llm_label)

        start = time.monotonic()
        try:
            response = await self._openai.chat.completions.create(
                model=self._model,
                messages=messages,
                response_format={
                    "type": "json_schema",
                    "json_schema": _RESPONSE_JSON_SCHEMA,
                },
                temperature=0.0,
                seed=42,
                max_tokens=self._max_output_tokens,
                timeout=self._timeout_s,
            )
        except Exception as e:  # noqa: BLE001 — classify below
            classification = _classify_openai_error(e)
            log_extra = {
                "s3_key": canonical_crop_s3_key,
                "label": llm_label[:80],
                "error_type": type(e).__name__,
                "error": str(e)[:300],
            }
            if classification == "terminal":
                logger.warning("alias_generation_openai_terminal", extra=log_extra)
                raise AliasGenerationTerminal(f"{type(e).__name__}: {e}") from e
            logger.warning("alias_generation_openai_retryable", extra=log_extra)
            raise AliasGenerationRetryable(f"{type(e).__name__}: {e}") from e

        latency_ms = int((time.monotonic() - start) * 1000)
        raw_text = (response.choices[0].message.content or "").strip()
        validated = _parse_and_validate(raw_text, s3_key=canonical_crop_s3_key)
        cost_usd = _estimate_cost_usd(self._model, response)

        logger.info(
            "alias_generation_success",
            extra={
                "s3_key": canonical_crop_s3_key,
                "label": llm_label[:80],
                "alias_count": len(validated.aliases),
                "model": self._model,
                "prompt_version": ALIAS_GENERATION_PROMPT_VERSION,
                "cost_usd": cost_usd,
                "latency_ms": latency_ms,
            },
        )
        return AliasGenerationResult(
            aliases=list(validated.aliases),
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            prompt_version=ALIAS_GENERATION_PROMPT_VERSION,
            model=self._model,
        )

    # ---------- internals ----------

    def _download_crop(self, s3_key: str) -> bytes:
        try:
            data = self._s3.get_object_bytes(s3_key)
        except Exception as e:  # noqa: BLE001 — classify by str
            # boto / botocore exceptions are "retryable" for network, but
            # NoSuchKey is permanent. Without importing botocore here
            # (would create a heavy dep), check by message.
            msg = str(e)
            if "NoSuchKey" in msg or "NotFound" in msg or "404" in msg:
                raise AliasGenerationTerminal(
                    f"canonical_crop_s3_key missing: {s3_key}"
                ) from e
            raise AliasGenerationRetryable(f"s3 download failed: {e}") from e

        if data is None:
            raise AliasGenerationTerminal(
                f"canonical_crop_s3_key returned None: {s3_key}"
            )
        if not data:
            raise AliasGenerationTerminal(
                f"canonical_crop_s3_key returned empty bytes: {s3_key}"
            )
        if len(data) > _MAX_IMAGE_BYTES:
            raise AliasGenerationTerminal(
                f"canonical_crop too large: {len(data)} > {_MAX_IMAGE_BYTES} "
                f"({s3_key})"
            )
        return data

    def _build_messages(self, *, data_url: str, label: str) -> list[dict[str, Any]]:
        user_text = AliasGenerationPrompt.USER_TEMPLATE.format(label=label)
        return [
            {"role": "system", "content": AliasGenerationPrompt.SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": data_url,
                            "detail": self._image_detail,
                        },
                    },
                ],
            },
        ]
    def _build_messages_text_only(
        self, *, label: str,
    ) -> list[dict[str, Any]]:
        """No-image variant — label only, no image_url content part.

        getattr fallback: CI/prod run against the PyPI contracts,
        which may predate USER_TEMPLATE_NO_IMAGE. Once the contracts
        release lands the attribute exists and is preferred.
        """
        template = getattr(
            AliasGenerationPrompt,
            "USER_TEMPLATE_NO_IMAGE",
            _FALLBACK_USER_TEMPLATE_NO_IMAGE,
        )
        user_text = template.format(label=label)
        return [
            {"role": "system", "content": AliasGenerationPrompt.SYSTEM},
            {"role": "user", "content": user_text},
        ]


def _to_data_url(image_bytes: bytes) -> str:
    """Encode bytes as a base64 data URL OpenAI vision accepts.

    MIME-sniffing the canonical_crop is overkill — every crop the
    enumerate worker writes is a JPEG. Hard-coding ``image/jpeg``
    saves a dependency on imghdr / python-magic; if the worker ever
    starts uploading PNGs, OpenAI accepts those under the same data
    URL prefix and the test would still pass.
    """
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _parse_and_validate(
    raw_text: str, *, s3_key: str,
) -> AliasGenerationResponse:
    """Parse JSON → AliasGenerationResponse. Any failure is terminal
    for this entry: a future re-run will hit the same prompt + same
    image and fail the same way unless the prompt is bumped."""
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        logger.warning(
            "alias_generation_json_parse_failed",
            extra={
                "s3_key": s3_key,
                "error": str(e)[:200],
                "raw_head": raw_text[:200],
            },
        )
        raise AliasGenerationTerminal(f"json_parse_failed: {e}") from e
    
    # v2.0: defensive cleanup — LLM occasionally emits a comma-joined
    # list as one string despite the prompt. Split on comma + dedup.
    # NO length filter here — would kill short brand transliterations
    # ('달심'); generic-word removal is the prompt's job (it can tell
    # brand vs category, this code can't).
    if isinstance(data, dict) and isinstance(data.get("aliases"), list):
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in data["aliases"]:
            if not isinstance(raw, str):
                continue
            for part in raw.split(","):
                p = part.strip()
                if not p:
                    continue
                key = p.casefold()
                if key in seen:
                    continue
                seen.add(key)
                cleaned.append(p)
        data["aliases"] = cleaned

    try:
        return AliasGenerationResponse.model_validate(data)
    except ValidationError as e:
        logger.warning(
            "alias_generation_schema_validation_failed",
            extra={"s3_key": s3_key, "error": str(e)[:200]},
        )
        raise AliasGenerationTerminal(f"schema_validation_failed: {e}") from e


def _classify_openai_error(err: Exception) -> str:
    """Return ``"retryable"`` | ``"terminal"``.

    Mirrors ``image_caption.engines.openai_client._classify_error``
    but inlined here to avoid cross-feature imports (loose-coupling
    rule). Defaults to ``"retryable"`` on unknown — the CLI bounds
    overall runtime, the realtime hook fires-and-forgets, so an
    unknown that happens to be permanent is not a footgun.
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
    return "retryable"


def _estimate_cost_usd(model: str, response: Any) -> float:
    """Best-effort cost estimate. Uses the same gpt-4o-mini pricing
    table as ``image_caption.engines.openai_client``. Inlined to
    preserve loose-coupling.
    """
    pricing = {
        "gpt-4o-mini": {"input": 0.15, "cached_input": 0.075, "output": 0.60},
        "gpt-4o": {"input": 2.50, "cached_input": 1.25, "output": 10.00},
    }.get(model, {"input": 2.50, "cached_input": 1.25, "output": 10.00})

    usage = getattr(response, "usage", None)
    if usage is None:
        return 0.0
    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    cached = 0
    details = getattr(usage, "prompt_tokens_details", None)
    if details is not None:
        cached = int(getattr(details, "cached_tokens", 0) or 0)
    non_cached = max(0, prompt_tokens - cached)
    return (
        non_cached * pricing["input"] / 1_000_000
        + cached * pricing["cached_input"] / 1_000_000
        + completion_tokens * pricing["output"] / 1_000_000
    )
