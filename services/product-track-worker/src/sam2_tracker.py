"""Concrete :class:`heimdex_media_pipelines.product_track.Sam2Tracker`
implementation.

Phase 3c-B: real SAM2 video propagation against a single scene's
proxy video. The lib's ``propagate_within_candidate_scenes`` calls
``track(scene_id, anchor_bbox, anchor_keyframe, scene_video_url,
sample_fps)`` per candidate; per-scene errors are caught + logged
upstream so a single bad scene never aborts the whole job (the
Phase 3c-A F4 ``_CountingSam2Tracker`` then catches the
stage-wide-failure case if every scene errors).

Implementation flow:

  1. Open the proxy video. ``scene_video_url`` may be presigned S3
     HTTP, plain HTTP, or a local path; OpenCV's ``VideoCapture``
     handles all three. (S3 ``s3://`` URLs require explicit
     download first — tracker doesn't see those because the worker
     resolves to presigned HTTP before passing.)
  2. Sample frames at ``sample_fps``. The capture's reported FPS
     drives the stride; sub-sampling is done on the input side so
     SAM2 never sees frames it won't be asked about.
  3. Anchor placement: Phase 3c-B v1 uses the first sampled frame
     as the anchor — the lib already passes us the keyframe of an
     accepted candidate scene, so anchor placement is approximate
     but adequate for calibration. A future revision may switch to
     phash-nearest matching against ``anchor_keyframe`` if
     calibration motivates it.
  4. Initialize SAM2's video predictor with ``anchor_bbox``.
  5. Propagate forward + backward across the sampled frames; the
     predictor returns a per-frame mask + confidence.
  6. Convert each mask to an axis-aligned bbox. Empty masks (SAM2
     lost the object) emit a low-confidence sample so window
     assembly's threshold filter drops them naturally.

Failure modes (per ``Sam2Tracker`` contract — raise on any of
these so the lib's per-scene try/except records the failure and
continues):
  * Scene proxy missing / S3 404 → ``RuntimeError``.
  * Anchor bbox falls outside frame bounds → ``ValueError``.
  * SAM2 OOM → ``RuntimeError`` (CUDA propagates as RuntimeError).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from heimdex_media_pipelines.product_track.sam2_pass import (
    BBoxXYWH,
    TrackedSample,
)

if TYPE_CHECKING:  # pragma: no cover
    from PIL import Image


logger = logging.getLogger(__name__)


class Sam2TrackerImpl:
    """Real SAM2 video predictor wrapper.

    The model is loaded once via :func:`src.sam2_loader.load_sam2`
    (singleton) and reused across track calls. Per-call work is
    bounded by scene length × ``sample_fps`` — typical 5–15s
    candidate scenes at 5fps yield 25–75 frames per call.
    """

    def __init__(self, *, model_id: str) -> None:
        self._model_id = model_id

    def track(
        self,
        *,
        scene_id: str,
        anchor_bbox: BBoxXYWH,
        anchor_keyframe: "Image.Image",
        scene_video_url: str,
        sample_fps: int,
    ) -> list[TrackedSample]:
        # Lazy imports — keep module-import cheap for tests.
        import cv2
        import numpy as np
        import torch

        from src.sam2_loader import load_sam2

        loaded = load_sam2(model_id=self._model_id)

        # ── 1. Open the proxy video.
        cap = cv2.VideoCapture(scene_video_url)
        if not cap.isOpened():
            raise RuntimeError(
                f"failed to open scene video for SAM2 tracking "
                f"(scene_id={scene_id} url={scene_video_url})"
            )

        try:
            frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            source_fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

            # ── 2. Sample frames at sample_fps.
            stride = max(1, int(round(source_fps / max(sample_fps, 1))))
            sampled_frames: list[tuple[int, "np.ndarray"]] = []
            frame_idx = 0
            while True:
                ok, bgr = cap.read()
                if not ok:
                    break
                if frame_idx % stride == 0:
                    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                    sampled_frames.append((frame_idx, rgb))
                frame_idx += 1
                if total_frames and frame_idx >= total_frames:
                    break
        finally:
            cap.release()

        if not sampled_frames:
            # Empty scene (proxy decoded zero frames) — surface as a
            # runtime error so the lib's per-scene try/except marks
            # this scene as failed. Checked BEFORE the bbox bounds
            # check so corrupted-proxy cases (where metadata is 0x0)
            # surface as the correct error class.
            raise RuntimeError(
                f"no frames decoded from scene proxy "
                f"(scene_id={scene_id} url={scene_video_url})"
            )

        # If metadata reported 0x0 but we still got frames, fall
        # back to the actual decoded frame's dimensions.
        if frame_width <= 0 or frame_height <= 0:
            sampled_h, sampled_w = sampled_frames[0][1].shape[:2]
            frame_width = sampled_w
            frame_height = sampled_h

        # Anchor bbox bounds check — surface a clear ``ValueError``
        # rather than letting SAM2's predictor silently produce
        # garbage masks for an off-frame bbox.
        if (
            anchor_bbox.x < 0
            or anchor_bbox.y < 0
            or anchor_bbox.x + anchor_bbox.width > frame_width
            or anchor_bbox.y + anchor_bbox.height > frame_height
        ):
            raise ValueError(
                f"anchor_bbox {anchor_bbox} falls outside frame "
                f"{frame_width}x{frame_height} for scene_id={scene_id}"
            )

        # ── 3. Anchor selection — first sampled frame (Phase 3c-B v1).
        anchor_idx = 0

        # ── 4. Initialise SAM2 video predictor + add anchor box.
        # The transformers SAM2 video API surface is exercised
        # against a fake model in unit tests; calibration on
        # staging goldens validates against the real model's actual
        # call shape.
        frames_np = np.stack([f for _, f in sampled_frames], axis=0)
        with torch.inference_mode():
            inputs = loaded.processor(
                videos=frames_np,
                return_tensors="pt",
            ).to(loaded.device)
            video_state = loaded.model.init_state(
                pixel_values=inputs["pixel_values"],
            )
            loaded.model.add_new_points_or_box(
                state=video_state,
                frame_idx=anchor_idx,
                obj_id=1,
                box=[
                    anchor_bbox.x,
                    anchor_bbox.y,
                    anchor_bbox.x + anchor_bbox.width,
                    anchor_bbox.y + anchor_bbox.height,
                ],
            )

            # ── 5. Propagate. The video model emits masks per
            # sampled frame as it walks the timeline.
            samples: list[TrackedSample] = []
            for prop_idx, _obj_ids, masks in loaded.model.propagate_in_video(
                video_state,
            ):
                if prop_idx >= len(sampled_frames):
                    continue  # defensive — should never exceed
                source_frame_idx, _ = sampled_frames[prop_idx]
                # ``masks`` is shape (num_obj, H, W) — we added
                # exactly one object so index 0 is the only mask.
                mask_t = masks[0]
                mask_score = getattr(masks, "score", None)
                mask_conf = float(
                    mask_score
                    if mask_score is not None
                    else mask_t.float().mean().item()
                )
                mask_np = mask_t.detach().cpu().numpy()
                bbox = _mask_to_bbox(mask_np)
                frame_ts_ms = int(source_frame_idx * 1000 / source_fps)
                if bbox is None:
                    # Empty mask — SAM2 lost the object. Emit a
                    # low-confidence sample with the original
                    # anchor bbox as a placeholder; the lib's
                    # window-assembly threshold filters drop it.
                    samples.append(TrackedSample(
                        frame_timestamp_ms=frame_ts_ms,
                        bbox=anchor_bbox,
                        mask_confidence=0.0,
                        frame_width=frame_width,
                        frame_height=frame_height,
                    ))
                    continue
                samples.append(TrackedSample(
                    frame_timestamp_ms=frame_ts_ms,
                    bbox=bbox,
                    mask_confidence=mask_conf,
                    frame_width=frame_width,
                    frame_height=frame_height,
                ))

        # The lib's contract requires monotonic ascending order by
        # ``frame_timestamp_ms``. Forward+backward propagation may
        # emit out-of-order; sort defensively.
        samples.sort(key=lambda s: s.frame_timestamp_ms)
        return samples


def _mask_to_bbox(mask_np) -> BBoxXYWH | None:
    """Convert a binary mask (numpy bool / uint8 array of shape
    ``(H, W)``) to an axis-aligned :class:`BBoxXYWH`.

    Returns ``None`` when the mask has no foreground pixels (SAM2
    "object disappeared" case). Caller decides how to surface that —
    Phase 3c-B emits a low-confidence sample with the anchor bbox
    as a placeholder so the window-assembly threshold filter drops
    it without disrupting the timeline.
    """
    import numpy as np

    bool_mask = mask_np.astype(bool)
    rows = np.any(bool_mask, axis=1)
    cols = np.any(bool_mask, axis=0)
    if not rows.any() or not cols.any():
        return None
    y_min = int(np.argmax(rows))
    y_max = int(len(rows) - 1 - np.argmax(rows[::-1]))
    x_min = int(np.argmax(cols))
    x_max = int(len(cols) - 1 - np.argmax(cols[::-1]))
    return BBoxXYWH(
        x=x_min,
        y=y_min,
        width=max(1, x_max - x_min + 1),
        height=max(1, y_max - y_min + 1),
    )
