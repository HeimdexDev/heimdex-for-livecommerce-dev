"""OpenAICaptionEngine — conforms to CaptionEngine Protocol.

Responsibilities:
  1. Load image bytes from disk, MIME-sniff, base64-encode.
  2. Build a prompt-cache-friendly message list:
         [system, *few_shot_turns, user_with_image]
  3. Delegate the HTTP call to OpenAICaptionClient.
  4. Parse the structured JSON response.
  5. Run person-safety post-validation.
  6. Return a CaptionResult (or raise a typed engine error).

This module owns zero I/O policy (retries, budget, concurrency) — all of
that lives in OpenAICaptionClient. Swap clients for fakes in tests.
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
from pathlib import Path
from typing import Any

from .base import (
    CaptionResult,
    PersonSafetyViolation,
    TerminalEngineError,
    TokenUsage,
)
from .openai_client import OpenAICaptionClient
from .openai_prompt import (
    BANNED_PERSON_TERMS,
    FEW_SHOT_TURNS,
    JSON_SCHEMA,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    USER_INSTRUCTION,
)
from .post_validation import assert_person_safety

logger = logging.getLogger(__name__)

_MAX_IMAGE_BYTES = 20 * 1024 * 1024  # OpenAI's per-image limit is ~20MB


class OpenAICaptionEngine:
    name: str = "openai"

    def __init__(
        self,
        *,
        client: OpenAICaptionClient,
        image_detail: str = "low",
        banned_terms: list[str] | None = None,
        prompt_version: str = PROMPT_VERSION,
    ) -> None:
        if image_detail not in ("low", "high", "auto"):
            raise ValueError(f"invalid image_detail: {image_detail!r}")
        self._client = client
        self._image_detail = image_detail
        self._banned_terms = banned_terms or BANNED_PERSON_TERMS
        self._prompt_version = prompt_version

    def close(self) -> None:
        self._client.close()

    def caption(
        self,
        image_path: Path | str,
        hints: dict[str, Any] | None = None,
    ) -> CaptionResult:
        path = Path(image_path)
        if not path.exists():
            raise TerminalEngineError(f"image not found: {path}")

        image_bytes = path.read_bytes()
        if not image_bytes:
            raise TerminalEngineError(f"image is empty: {path}")
        if len(image_bytes) > _MAX_IMAGE_BYTES:
            raise TerminalEngineError(
                f"image too large for OpenAI API: "
                f"{len(image_bytes)} > {_MAX_IMAGE_BYTES}"
            )

        mime = _sniff_mime(path)
        data_url = _to_data_url(image_bytes, mime)

        messages = self._build_messages(data_url, hints or {})

        call = self._client.call(
            messages=messages,
            response_format=JSON_SCHEMA,
        )

        structured, parse_error = _parse_structured(call.text)
        if parse_error is not None:
            logger.warning(
                "openai_caption_parse_failed",
                extra={
                    "error": parse_error,
                    "raw_snippet": call.text[:500],
                    "path": str(path),
                },
            )
            return CaptionResult(
                caption="",
                prompt_version=self._prompt_version,
                model=call.model,
                usage=call.usage,
                structured=None,
                latency_ms=call.latency_ms,
                validation_failure=f"parse_error:{parse_error}",
            )

        caption_text = str(structured.get("caption", "")).strip()
        has_person = bool(structured.get("has_person", False))

        try:
            assert_person_safety(caption_text, has_person, self._banned_terms)
        except PersonSafetyViolation as e:
            logger.error(
                "openai_caption_person_safety_violation",
                extra={
                    "path": str(path),
                    "has_person": has_person,
                    "caption_snippet": caption_text[:200],
                    "error": str(e),
                    "prompt_version": self._prompt_version,
                    "model": call.model,
                },
            )
            return CaptionResult(
                caption="",
                prompt_version=self._prompt_version,
                model=call.model,
                usage=call.usage,
                structured=structured,
                latency_ms=call.latency_ms,
                validation_failure="person_terms_leaked",
            )

        return CaptionResult(
            caption=caption_text,
            prompt_version=self._prompt_version,
            model=call.model,
            usage=call.usage,
            structured=structured,
            latency_ms=call.latency_ms,
            validation_failure=None,
        )

    def _build_messages(
        self,
        data_url: str,
        hints: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Assemble the chat completion message list.

        Layout is stable across calls so OpenAI prompt caching reuses the
        prefix: system + few_shot_turns are always byte-identical; only
        the final user turn varies per image.
        """

        # Optional hint string — filename and library_name give the model
        # soft context without polluting the base prompt. Keep it short.
        hint_parts: list[str] = []
        file_name = hints.get("file_name")
        if file_name:
            hint_parts.append(f"파일명: {file_name}")
        library_name = hints.get("library_name")
        if library_name:
            hint_parts.append(f"라이브러리: {library_name}")
        hint_line = f"\n(참고: {', '.join(hint_parts)})" if hint_parts else ""

        user_content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": USER_INSTRUCTION + hint_line,
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": data_url,
                    "detail": self._image_detail,
                },
            },
        ]

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]
        messages.extend(FEW_SHOT_TURNS)
        messages.append({"role": "user", "content": user_content})
        return messages


def _sniff_mime(path: Path) -> str:
    guess, _ = mimetypes.guess_type(str(path))
    if guess and guess.startswith("image/"):
        return guess
    suffix = path.suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gif":
        return "image/gif"
    return "image/jpeg"


def _to_data_url(image_bytes: bytes, mime: str) -> str:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _parse_structured(raw: str) -> tuple[dict[str, Any], str | None]:
    if not raw:
        return {}, "empty_response"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        return {}, f"json_decode:{e.msg}"
    if not isinstance(parsed, dict):
        return {}, "not_object"
    if "caption" not in parsed:
        return parsed, "missing_caption_field"
    return parsed, None
