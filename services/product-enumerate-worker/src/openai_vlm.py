"""Production :class:`VlmClient` impl backed by OpenAI gpt-4o-mini.

Encodes each keyframe as a base64 data URL and invokes the
chat-completion endpoint in JSON mode with the prompts from the
contracts ``EnumerationPrompt``.

Failure modes (matching ``ProductScanFailed.error_code``):
* HTTP timeout / 5xx after retries → ``llm_timeout``
* JSON-mode parse failure or schema mismatch → ``llm_schema_mismatch``

The client returns :class:`VlmDetectionBatch` instances directly so
the pipeline can consume them without a re-shape.
"""

from __future__ import annotations

import base64
import io
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from heimdex_media_pipelines.product_enum.vlm_client import (
    EnumerationDetection,
    VlmDetectionBatch,
)

if TYPE_CHECKING:  # pragma: no cover
    from PIL import Image

logger = logging.getLogger(__name__)


# Approximate cost (USD) per gpt-4o-mini vision call with ~10 images
# at low/medium detail. Used as a fallback when the API response
# doesn't carry token usage. Real cost is computed from `usage` when
# available.
_FALLBACK_COST_PER_BATCHED_CALL_USD = 0.005

_RESPONSE_SCHEMA = {
    "name": "product_enumeration_response",
    # Without strict=True, OpenAI's json_schema is advisory: the model
    # is free to omit "required" fields and the validator silently
    # drops every partial item. Staging vision enumeration was
    # consistently returning 0 clusters 2026-05-17/18 because of this
    # exact gap. Same silent-fail-open pattern as the OCR Aircloud
    # incident — see memory `feedback_external_lib_eager_init_fail_loud`.
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["products"],
        "properties": {
            "products": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "scene_id",
                        "frame_idx",
                        "label",
                        "bbox_xywh",
                        "confidence",
                    ],
                    "properties": {
                        "scene_id": {"type": "string"},
                        "frame_idx": {"type": "integer", "minimum": 0},
                        "label": {"type": "string"},
                        "bbox_xywh": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "minItems": 4,
                            "maxItems": 4,
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                        },
                    },
                },
            },
        },
    },
}


@dataclass
class OpenAIVlmClient:
    """Concrete VLM client. Conforms to
    :class:`heimdex_media_pipelines.product_enum.vlm_client.VlmClient`.

    Constructed once per worker boot and reused across job calls.
    """

    api_key: str
    model: str = "gpt-4o-mini"
    timeout_sec: float = 30.0
    max_retries: int = 3
    fallback_cost_usd: float = _FALLBACK_COST_PER_BATCHED_CALL_USD

    def __post_init__(self) -> None:
        from openai import OpenAI
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required")
        self._client = OpenAI(
            api_key=self.api_key,
            timeout=self.timeout_sec,
            max_retries=self.max_retries,
        )

    def detect_products(
        self,
        *,
        keyframes: list[tuple[str, int, "Image.Image"]],
        system_prompt: str,
        user_prompt: str,
    ) -> VlmDetectionBatch:
        if not keyframes:
            return VlmDetectionBatch(detections=[], cost_usd=0.0)

        # Build a multi-image user message — each image is tagged with
        # its scene_id + frame_idx in a preceding text part so the
        # model can echo them back on each detection.
        content: list[dict[str, object]] = [{"type": "text", "text": user_prompt}]
        for scene_id, frame_idx, image in keyframes:
            content.append({
                "type": "text",
                "text": f"scene_id={scene_id} frame_idx={frame_idx}",
            })
            content.append({
                "type": "image_url",
                "image_url": {"url": _image_to_data_url(image), "detail": "low"},
            })

        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": _RESPONSE_SCHEMA,
                },
            )
        except Exception as exc:
            # Wrap so the dispatcher can surface a stable error_code.
            logger.exception("openai_vlm_call_failed")
            raise VlmTimeoutError(str(exc)) from exc

        if not resp.choices:
            raise VlmSchemaError("OpenAI returned no choices")
        message = resp.choices[0].message
        if message.content is None:
            raise VlmSchemaError("OpenAI returned no content")

        try:
            parsed = json.loads(message.content)
        except json.JSONDecodeError as exc:
            raise VlmSchemaError(f"non-JSON response: {exc}") from exc

        items = parsed.get("products")
        if not isinstance(items, list):
            raise VlmSchemaError("response.products is not a list")

        detections: list[EnumerationDetection] = []
        for item in items:
            try:
                bbox = tuple(int(v) for v in item["bbox_xywh"])
                if len(bbox) != 4:
                    raise ValueError("bbox_xywh must be length 4")
                detections.append(
                    EnumerationDetection(
                        keyframe_scene_id=str(item["scene_id"]),
                        keyframe_frame_idx=int(item["frame_idx"]),
                        label=str(item["label"]),
                        bbox_xywh=bbox,
                        confidence=float(item["confidence"]),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                # Inline the item + error in the message body — Aircloud's
                # log formatter strips `extra=` keys, leaving us blind
                # when the model returns partial items. Keep the extra
                # dict too so structured loggers downstream still index.
                item_repr = json.dumps(item, ensure_ascii=False, default=str)[:500]
                logger.warning(
                    "openai_vlm_dropped_malformed_item err=%s item=%s",
                    exc,
                    item_repr,
                    extra={"item": item, "error": str(exc)},
                )

        cost = self._estimate_cost(resp)
        return VlmDetectionBatch(
            detections=detections,
            cost_usd=cost,
            debug={"model": self.model, "n_returned": len(items)},
        )

    def _estimate_cost(self, resp: object) -> float:
        """Best-effort cost from response.usage; fall back to a flat
        per-call estimate when the SDK doesn't surface token counts."""
        usage = getattr(resp, "usage", None)
        if usage is None:
            return self.fallback_cost_usd
        # gpt-4o-mini: $0.15/1M input, $0.60/1M output (2026 pricing).
        # Vision tokens count as input; this is a rough estimate only.
        in_tok = getattr(usage, "prompt_tokens", 0) or 0
        out_tok = getattr(usage, "completion_tokens", 0) or 0
        return (in_tok / 1_000_000) * 0.15 + (out_tok / 1_000_000) * 0.60


# ---------- exceptions ----------

class VlmTimeoutError(Exception):
    """Raised when the OpenAI call fails after retries — maps to
    ``error_code="llm_timeout"`` on the API fail callback."""


class VlmSchemaError(Exception):
    """Raised when the response can't be parsed into the expected
    schema — maps to ``error_code="llm_schema_mismatch"``."""


# ---------- helpers ----------

def _image_to_data_url(image: "Image.Image") -> str:
    """PIL → base64 data URL. Re-encodes to JPEG at quality 80 to bound
    the request body size — keyframes from S3 may be lossless PNG and
    cause unnecessarily large payloads if passed through verbatim."""
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=80, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"
