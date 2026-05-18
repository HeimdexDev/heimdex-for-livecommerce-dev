"""Production :class:`VlmClient` impl backed by **OWLv2 + gpt-4o-mini**.

The class name is kept (``OpenAIVlmClient``) so existing wiring in
``worker.py`` / ``tasks/enumerate.py`` doesn't change, but the
internals are now a 2-stage pipeline:

* **Stage 1 — OWLv2** (open-vocab detector): localizes products from
  generic text queries. Produces tight bboxes that are consistently
  better-fitting than gpt-4o-mini's free-form xywh output.
* **Stage 2 — gpt-4o-mini per crop**: each OWLv2 bbox is cropped from
  the original keyframe and sent with ``LABEL_PROMPT_SYSTEM`` for a
  short Korean noun phrase + an ``is_product`` flag. Non-product
  crops (faces, studio props, blurry artifacts) are dropped, which
  filters OWLv2 false positives.

The :class:`VlmClient` protocol still gets called per keyframe batch
by ``heimdex_media_pipelines.product_enum.pipeline.enumerate_products``;
we set ``openai_batch_size=1`` so each call processes one keyframe.

Failure modes (matching ``ProductScanFailed.error_code``):
* OWLv2 forward-pass failure on every keyframe in the run → bubbles
  up as a generic exception (dispatcher maps to ``internal_error``).
* OpenAI HTTP timeout / 5xx after retries on every crop → propagated
  as :class:`VlmTimeoutError` → ``llm_timeout``.
* JSON-mode parse failure / schema mismatch on every crop →
  :class:`VlmSchemaError` → ``llm_schema_mismatch``.

Per-crop failures are logged and *kept* with an OWLv2 fallback label
rather than aborting the whole job — one flaky API call should not
poison N-1 valid detections from the same keyframe.
"""

from __future__ import annotations

import base64
import concurrent.futures
import io
import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from heimdex_media_pipelines.product_enum.vlm_client import (
    EnumerationDetection,
    VlmDetectionBatch,
)

from src.owlv2_prompts import (
    DEFAULT_OWLV2_QUERIES,
    LABEL_JSON_SCHEMA,
    LABEL_PROMPT_SYSTEM,
    OWLV2_PROMPT_VERSION,
)

if TYPE_CHECKING:  # pragma: no cover
    import torch
    from PIL import Image
    from transformers import Owlv2ForObjectDetection, Owlv2Processor

logger = logging.getLogger(__name__)


# Approximate cost (USD) per gpt-4o-mini vision call on a single
# bbox-sized crop at detail=low. Used as a fallback when the API
# response doesn't carry token usage. Real cost is computed from
# ``response.usage`` when available.
_FALLBACK_COST_PER_CROP_CALL_USD = 0.0003


@dataclass
class OpenAIVlmClient:
    """Concrete VLM client. Conforms to
    :class:`heimdex_media_pipelines.product_enum.vlm_client.VlmClient`.

    Constructed once per worker boot — see ``worker.py`` for the
    OWLv2 model/processor preload. The OpenAI HTTP client is lazy and
    creates connections on first use.
    """

    api_key: str
    # OWLv2 is preloaded at worker boot (heavy: ~600MB weights) and
    # injected here so per-job dispatch doesn't pay the load cost on
    # every message.
    owlv2_processor: "Owlv2Processor"
    owlv2_model: "Owlv2ForObjectDetection"
    owlv2_device: "torch.device"
    queries: list[str] = field(default_factory=lambda: list(DEFAULT_OWLV2_QUERIES))
    model: str = "gpt-4o-mini"
    timeout_sec: float = 30.0
    max_retries: int = 3
    # Stage-1 (OWLv2) tunables — defaults mirror WorkerSettings.
    threshold: float = 0.475
    nms_iou: float = 0.5
    max_dets_per_keyframe: int = 5
    max_image_side: int = 960
    crop_pad_frac: float = 0.05
    # Stage-2 (gpt-4o-mini) parallelism.
    label_concurrency: int = 8
    fallback_cost_per_crop_usd: float = _FALLBACK_COST_PER_CROP_CALL_USD

    def __post_init__(self) -> None:
        from openai import OpenAI

        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required")
        if not self.queries:
            raise ValueError("OWLv2 queries list is empty")
        self._client = OpenAI(
            api_key=self.api_key,
            timeout=self.timeout_sec,
            max_retries=self.max_retries,
        )

    # ------------------------------------------------------------------
    # VlmClient protocol
    # ------------------------------------------------------------------

    def detect_products(
        self,
        *,
        keyframes: list[tuple[str, int, "Image.Image"]],
        system_prompt: str,
        user_prompt: str,
    ) -> VlmDetectionBatch:
        """Run OWLv2 + per-crop labeling on each keyframe in the batch.

        ``system_prompt`` and ``user_prompt`` are accepted to satisfy
        the protocol but ignored — the label prompt is fixed inside
        the client (``LABEL_PROMPT_SYSTEM``) and OWLv2 takes a query
        list, not a free-form prompt. tasks/enumerate.py passes empty
        strings on purpose.
        """
        del system_prompt, user_prompt  # ignored — see docstring

        if not keyframes:
            return VlmDetectionBatch(detections=[], cost_usd=0.0)

        all_detections: list[EnumerationDetection] = []
        total_cost = 0.0
        owl_keyframes_processed = 0
        owl_detections_before_label = 0
        dropped_non_product = 0
        label_failures = 0

        for scene_id, frame_idx, image in keyframes:
            try:
                owl_boxes = self._run_owlv2_on_keyframe(image)
            except Exception:  # noqa: BLE001 — log + skip frame
                # Surface as a timeout-class error if every keyframe
                # eventually fails — handled by the outer aggregator
                # below via ``owl_keyframes_processed``.
                logger.exception(
                    "owlv2_keyframe_failed",
                    extra={"scene_id": scene_id, "frame_idx": frame_idx},
                )
                continue
            owl_keyframes_processed += 1
            owl_detections_before_label += len(owl_boxes)

            if not owl_boxes:
                continue

            labeled, batch_cost, dropped, failed = self._label_crops_parallel(
                image=image,
                scene_id=scene_id,
                frame_idx=frame_idx,
                owl_boxes=owl_boxes,
            )
            total_cost += batch_cost
            dropped_non_product += dropped
            label_failures += failed
            all_detections.extend(labeled)

        if owl_keyframes_processed == 0 and keyframes:
            # Every keyframe in this call failed OWLv2. Treat as a
            # timeout-class failure so the dispatcher records
            # ``error_code=llm_timeout`` rather than ``internal_error``
            # (the user-facing distinction is "model unavailable" vs
            # "worker bug").
            raise VlmTimeoutError(
                "OWLv2 forward pass failed on every keyframe in batch"
            )

        debug = {
            "model": self.model,
            "owlv2_model": getattr(
                self.owlv2_model.config, "_name_or_path", "owlv2"
            ),
            "prompt_version": OWLV2_PROMPT_VERSION,
            "keyframes_in_batch": len(keyframes),
            "owl_detections_before_label": owl_detections_before_label,
            "dropped_non_product": dropped_non_product,
            "label_failures": label_failures,
        }
        return VlmDetectionBatch(
            detections=all_detections, cost_usd=total_cost, debug=debug,
        )

    # ------------------------------------------------------------------
    # Stage 1 — OWLv2
    # ------------------------------------------------------------------

    def _run_owlv2_on_keyframe(
        self, image: "Image.Image",
    ) -> list[tuple[int, int, int, int, str, float]]:
        """Return ``[(x, y, w, h, query_label, score), ...]`` in
        ORIGINAL-image pixel coordinates after class-agnostic NMS."""
        import torch

        orig_w, orig_h = image.size
        sent = self._resize_for_owlv2(image)
        sent_w, sent_h = sent.size

        inputs = self.owlv2_processor(
            text=[self.queries], images=sent, return_tensors="pt"
        ).to(self.owlv2_device)

        with torch.no_grad():
            outputs = self.owlv2_model(**inputs)

        target_sizes = torch.tensor(
            [[sent_h, sent_w]], device=self.owlv2_device
        )
        results = self.owlv2_processor.post_process_grounded_object_detection(
            outputs=outputs,
            target_sizes=target_sizes,
            threshold=self.threshold,
        )[0]

        scores = results["scores"].detach().cpu().tolist()
        boxes = results["boxes"].detach().cpu().tolist()
        label_ids = results["labels"].detach().cpu().tolist()

        sx = orig_w / sent_w
        sy = orig_h / sent_h

        raw: list[tuple[int, int, int, int, str, float]] = []
        for score, box, lid in zip(scores, boxes, label_ids):
            x1, y1, x2, y2 = box
            rx = max(0, int(round(x1)))
            ry = max(0, int(round(y1)))
            rw = max(1, int(round(x2 - x1)))
            rh = max(1, int(round(y2 - y1)))
            x_o = max(0, min(int(round(rx * sx)), orig_w - 1))
            y_o = max(0, min(int(round(ry * sy)), orig_h - 1))
            w_o = max(1, min(int(round(rw * sx)), orig_w - x_o))
            h_o = max(1, min(int(round(rh * sy)), orig_h - y_o))
            query = (
                self.queries[lid]
                if 0 <= lid < len(self.queries)
                else f"class_{lid}"
            )
            raw.append((x_o, y_o, w_o, h_o, query, float(score)))

        deduped = _class_agnostic_nms(raw, self.nms_iou)
        deduped.sort(key=lambda r: r[5], reverse=True)
        return deduped[: self.max_dets_per_keyframe]

    def _resize_for_owlv2(self, image: "Image.Image") -> "Image.Image":
        """Downscale so the long edge ≤ ``max_image_side``. OWLv2's
        processor internally pads to 960x960; passing already-resized
        images keeps memory bounded for HD keyframes."""
        from PIL import Image as PILImage

        w, h = image.size
        long_side = max(w, h)
        if long_side <= self.max_image_side:
            return image.convert("RGB") if image.mode != "RGB" else image
        scale = self.max_image_side / long_side
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        return image.convert("RGB").resize(
            (new_w, new_h), resample=PILImage.LANCZOS
        )

    # ------------------------------------------------------------------
    # Stage 2 — gpt-4o-mini per-crop labeling
    # ------------------------------------------------------------------

    def _label_crops_parallel(
        self,
        *,
        image: "Image.Image",
        scene_id: str,
        frame_idx: int,
        owl_boxes: list[tuple[int, int, int, int, str, float]],
    ) -> tuple[list[EnumerationDetection], float, int, int]:
        """Label every OWLv2 bbox in parallel. Returns
        ``(detections, cost_usd, dropped_non_product, label_failures)``.

        Drops ``is_product=False`` crops. Per-crop failures are logged
        and kept with the OWLv2 query as a fallback label — losing one
        flaky API call would otherwise discard a usable detection.
        """
        cost = 0.0
        dropped = 0
        failed = 0
        out: list[EnumerationDetection] = []

        def _process(
            box: tuple[int, int, int, int, str, float],
        ) -> tuple[
            tuple[int, int, int, int, str, float], bool, str, float, str | None,
        ]:
            x, y, w, h, query, score = box
            crop = _crop_with_padding(image, x, y, w, h, self.crop_pad_frac)
            try:
                is_product, label, call_cost = self._label_one_crop(crop)
            except VlmTimeoutError as exc:
                return box, False, "", 0.0, f"timeout: {exc}"
            except VlmSchemaError as exc:
                return box, False, "", 0.0, f"schema: {exc}"
            except Exception as exc:  # noqa: BLE001
                return box, False, "", 0.0, f"{type(exc).__name__}: {exc}"
            return box, is_product, label, call_cost, None

        max_workers = max(1, min(self.label_concurrency, len(owl_boxes)))
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers
        ) as pool:
            for box, is_product, label, call_cost, err in pool.map(
                _process, owl_boxes,
            ):
                x, y, w, h, query, score = box
                if err is not None:
                    failed += 1
                    logger.warning(
                        "label_crop_failed_falling_back_to_owl_query "
                        "scene=%s frame=%s owl_query=%s err=%s",
                        scene_id,
                        frame_idx,
                        query,
                        err,
                        extra={
                            "scene_id": scene_id,
                            "frame_idx": frame_idx,
                            "owl_query": query,
                            "error": err,
                        },
                    )
                    out.append(
                        EnumerationDetection(
                            keyframe_scene_id=scene_id,
                            keyframe_frame_idx=frame_idx,
                            label=query,
                            bbox_xywh=(x, y, w, h),
                            confidence=score,
                        )
                    )
                    continue
                cost += call_cost
                if not is_product:
                    dropped += 1
                    continue
                # gpt-4o-mini sometimes returns is_product=True with an
                # empty label — fall back to OWLv2's English query in
                # that case so downstream SigLIP2 clustering still has
                # something readable to display.
                final_label = label.strip() or query
                out.append(
                    EnumerationDetection(
                        keyframe_scene_id=scene_id,
                        keyframe_frame_idx=frame_idx,
                        label=final_label,
                        bbox_xywh=(x, y, w, h),
                        confidence=score,
                    )
                )

        return out, cost, dropped, failed

    def _label_one_crop(
        self, crop: "Image.Image",
    ) -> tuple[bool, str, float]:
        """One gpt-4o-mini call labeling a single crop. Returns
        ``(is_product, korean_label, cost_usd)``."""
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": LABEL_PROMPT_SYSTEM},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": _image_to_data_url(crop),
                                    "detail": "low",
                                },
                            }
                        ],
                    },
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": LABEL_JSON_SCHEMA,
                },
                temperature=0,
            )
        except Exception as exc:
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

        is_product = bool(parsed.get("is_product", False))
        label = str(parsed.get("label", "")).strip()
        cost = self._estimate_cost(resp)
        return is_product, label, cost

    # ------------------------------------------------------------------
    # cost
    # ------------------------------------------------------------------

    def _estimate_cost(self, resp: Any) -> float:
        """Best-effort cost from response.usage; fall back to a flat
        per-call estimate when the SDK doesn't surface token counts."""
        usage = getattr(resp, "usage", None)
        if usage is None:
            return self.fallback_cost_per_crop_usd
        # gpt-4o-mini: $0.15/1M input, $0.60/1M output (2026 pricing).
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
    """PIL → base64 JPEG data URL. Quality 80 bounds the request body
    size for HD keyframes that may arrive as lossless PNG from S3."""
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=80, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def _crop_with_padding(
    image: "Image.Image",
    x: int,
    y: int,
    w: int,
    h: int,
    pad_frac: float,
) -> "Image.Image":
    """PIL crop with a fractional padding margin clamped to the image.

    Mirrors ``detect_owl._crop_with_padding`` but on PIL (the worker
    already has the image as PIL from S3 download — converting via
    numpy round-trip would be wasted memory)."""
    W, H = image.size
    pad_x = int(round(w * pad_frac))
    pad_y = int(round(h * pad_frac))
    x1 = max(0, x - pad_x)
    y1 = max(0, y - pad_y)
    x2 = min(W, x + w + pad_x)
    y2 = min(H, y + h + pad_y)
    return image.crop((x1, y1, x2, y2))


def _iou_xywh(
    a: tuple[int, int, int, int],
    b: tuple[int, int, int, int],
) -> float:
    ax2, ay2 = a[0] + a[2], a[1] + a[3]
    bx2, by2 = b[0] + b[2], b[1] + b[3]
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter == 0:
        return 0.0
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def _class_agnostic_nms(
    detections: list[tuple[int, int, int, int, str, float]],
    iou_thresh: float,
) -> list[tuple[int, int, int, int, str, float]]:
    """OWLv2 fires multiple queries on the same object (e.g.,
    'a product box' and 'a product on a display table' both fire on
    the same item). Class-agnostic NMS dedupes across queries."""
    if not detections:
        return []
    ordered = sorted(detections, key=lambda d: d[5], reverse=True)
    kept: list[tuple[int, int, int, int, str, float]] = []
    for cand in ordered:
        cb = (cand[0], cand[1], cand[2], cand[3])
        if any(
            _iou_xywh(cb, (k[0], k[1], k[2], k[3])) > iou_thresh
            for k in kept
        ):
            continue
        kept.append(cand)
    return kept


