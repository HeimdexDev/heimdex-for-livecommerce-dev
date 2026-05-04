"""Concrete :class:`heimdex_media_pipelines.product_track.Sam2Tracker`
implementation.

Phase 3c-B (post-2026-05-04): real SAM2 video propagation against
a SINGLE full-video proxy with per-scene in-memory window slicing.
The lib's ``propagate_within_candidate_scenes`` calls
``track(scene_id, anchor_bbox, anchor_keyframe, full_video_path,
scene_start_ms, scene_end_ms, sample_fps)`` per candidate; per-scene
errors are caught + logged upstream so a single bad scene never
aborts the whole job (the Phase 3c-A F4 ``_CountingSam2Tracker``
then catches the stage-wide-failure case if every scene errors).

Implementation flow:

  1. Open the full-video proxy that the worker downloaded once
     per job message. ``full_video_path`` is a local filesystem
     path the worker manages; we never reach for a per-scene mp4.
  2. Seek to ``scene_start_ms`` via ``CAP_PROP_POS_MSEC``. The
     seek is keyframe-aligned — cv2 may decode from the keyframe
     BEFORE the requested ms — so the sampling loop drops any
     pre-roll frames whose timestamp is < ``scene_start_ms``.
  3. Sample frames at ``sample_fps`` cadence (timestamp-based, not
     stride-based — the seek decouples us from "frames since file
     start"). Stop the loop once the decoded timestamp exceeds
     ``scene_end_ms`` so we don't pay decode cost outside the
     candidate window.
  4. Anchor placement: Phase 3c-B v1 uses the first sampled frame
     as the anchor — the lib already passes us the keyframe of an
     accepted candidate scene, so anchor placement is approximate
     but adequate for calibration. A future revision may switch to
     phash-nearest matching against ``anchor_keyframe`` if
     calibration motivates it.
  5. Initialize SAM2's video predictor with ``anchor_bbox``.
  6. Propagate forward + backward across the sampled frames; the
     predictor returns a per-frame mask + confidence.
  7. Convert each mask to an axis-aligned bbox. Empty masks (SAM2
     lost the object) emit a low-confidence sample so window
     assembly's threshold filter drops them naturally.

Failure modes (per ``Sam2Tracker`` contract — raise on any of
these so the lib's per-scene try/except records the failure and
continues):
  * Proxy missing / unreadable → ``RuntimeError``.
  * No frames decoded inside the scene window → ``RuntimeError``
    (corrupted proxy, seek fell off the end, or the scene window
    is degenerate).
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
        full_video_path: str,
        scene_start_ms: int,
        scene_end_ms: int,
        sample_fps: int,
    ) -> list[TrackedSample]:
        # Lazy imports — keep module-import cheap for tests.
        import cv2
        import numpy as np
        import torch

        from src.sam2_loader import load_sam2

        loaded = load_sam2(model_id=self._model_id)

        # ── 1. Open the full-video proxy (worker downloaded it once
        #      per job; we get a local filesystem path).
        cap = cv2.VideoCapture(full_video_path)
        if not cap.isOpened():
            raise RuntimeError(
                f"failed to open proxy video for SAM2 tracking "
                f"(scene_id={scene_id} path={full_video_path})"
            )

        try:
            frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            source_fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)

            # ── 2. Seek to the scene window's start. CAP_PROP_POS_MSEC
            #      is keyframe-aligned, so cv2 may land on the keyframe
            #      BEFORE scene_start_ms. The sampling loop below
            #      drops any pre-roll frames whose timestamp falls
            #      below scene_start_ms; correctness, not just
            #      efficiency.
            cap.set(cv2.CAP_PROP_POS_MSEC, float(scene_start_ms))

            # ── 3. Sample frames at sample_fps cadence within the
            #      scene window. ``next_sample_ts_ms`` advances by
            #      ``sample_interval_ms`` after each accepted sample;
            #      a decoded frame whose timestamp falls between two
            #      sample boundaries is skipped.
            sample_interval_ms = max(1, int(round(1000.0 / max(sample_fps, 1))))
            sampled_frames: list[tuple[int, "np.ndarray"]] = []
            next_sample_ts_ms = scene_start_ms

            while True:
                # Query position BEFORE reading. CAP_PROP_POS_MSEC
                # returns the time of the NEXT frame to be decoded,
                # so this is the timestamp of the frame ``cap.read``
                # is about to return.
                pos_ms = float(cap.get(cv2.CAP_PROP_POS_MSEC))
                ok, bgr = cap.read()
                if not ok:
                    break
                # Past the scene end → stop. Don't pay further
                # decode cost outside the candidate window.
                if pos_ms > scene_end_ms:
                    break
                # Pre-roll from the keyframe-aligned seek → drop.
                if pos_ms < scene_start_ms:
                    continue
                # Inside the window but ahead of the next sample
                # boundary → skip (downsample to ``sample_fps``).
                if pos_ms < next_sample_ts_ms:
                    continue
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                sampled_frames.append((int(pos_ms), rgb))
                next_sample_ts_ms = int(pos_ms) + sample_interval_ms
        finally:
            cap.release()

        if not sampled_frames:
            # Zero frames decoded inside the requested window —
            # corrupted proxy, seek fell off the end, or the scene
            # window is degenerate. Surface as a runtime error so
            # the lib's per-scene try/except marks this scene as
            # failed. Checked BEFORE the bbox bounds check so
            # corrupted-proxy cases (where metadata is 0x0) surface
            # as the correct error class.
            raise RuntimeError(
                f"no frames decoded in scene window "
                f"(scene_id={scene_id} "
                f"scene_start_ms={scene_start_ms} "
                f"scene_end_ms={scene_end_ms} "
                f"path={full_video_path})"
            )

        # If metadata reported 0x0 but we still got frames, fall
        # back to the actual decoded frame's dimensions.
        if frame_width <= 0 or frame_height <= 0:
            sampled_h, sampled_w = sampled_frames[0][1].shape[:2]
            frame_width = sampled_w
            frame_height = sampled_h

        # Anchor bbox bounds — clamp to fit the frame instead of
        # rejecting outright. The 2026-05-04 staging incident
        # (catalog c9f7c69e) hit this path because the LLM
        # enumeration produced ``BBoxXYWH(220, 150, 250, 300)``
        # whose ``x + width = 470`` overflows a 406-wide proxy by
        # 64 px. Strict rejection F4'd every scene of that
        # product. Clamping is the right default — SAM2 still has
        # a usable anchor, and operators see the over-spec via the
        # warning log so they can chase the enumeration data
        # quality issue separately.
        clamped_bbox = _clamp_bbox_to_frame(
            anchor_bbox, frame_width=frame_width, frame_height=frame_height,
        )
        if clamped_bbox is None:
            # Bbox is entirely off-frame — origin past the right /
            # bottom edge, or width/height is zero / negative after
            # clamping. Nothing to track.
            raise ValueError(
                f"anchor_bbox {anchor_bbox} falls entirely outside frame "
                f"{frame_width}x{frame_height} for scene_id={scene_id}"
            )
        if clamped_bbox != anchor_bbox:
            logger.warning(
                "sam2_anchor_bbox_clamped",
                extra={
                    "scene_id": scene_id,
                    "original_bbox": (
                        anchor_bbox.x, anchor_bbox.y,
                        anchor_bbox.width, anchor_bbox.height,
                    ),
                    "clamped_bbox": (
                        clamped_bbox.x, clamped_bbox.y,
                        clamped_bbox.width, clamped_bbox.height,
                    ),
                    "frame_width": frame_width,
                    "frame_height": frame_height,
                },
            )

        # ── 3. Anchor selection — first sampled frame (Phase 3c-B v1).
        anchor_idx = 0

        # ── 4. SAM2 video tracking (transformers 5.5.4 API).
        #
        # The v5 API is fundamentally different from v4. Replaced:
        #
        #   v4:  processor(videos=..., return_tensors="pt") +
        #        model.init_state(pixel_values=...) +
        #        model.add_new_points_or_box(state, frame_idx, obj_id, box) +
        #        model.propagate_in_video(state)
        #
        #   v5:  processor.init_video_session(video=frames) → session
        #        processor.process_new_points_or_boxes_for_video_frame(
        #            session, frame_idx, obj_ids=[1],
        #            input_boxes=[[[x1, y1, x2, y2]]],
        #            original_size=(H, W),
        #        )
        #        for output in model.propagate_in_video_iterator(
        #            inference_session=session,
        #        ):
        #            output.pred_masks  # (batch, num_obj, H, W)
        #
        # Verified empirically inside the worker container against
        # ``transformers.Sam2VideoProcessor`` and
        # ``transformers.models.sam2_video.modeling_sam2_video.Sam2VideoInferenceSession``
        # signatures on 2026-05-04. The earlier ``init_state``
        # / ``add_new_points_or_box`` / ``propagate_in_video``
        # methods do not exist on ``Sam2VideoModel`` in v5.
        from PIL import Image as _PILImage  # noqa: PLC0415 — keep module-import cheap
        frames_pil = [_PILImage.fromarray(rgb) for _, rgb in sampled_frames]

        with torch.inference_mode():
            # 4a. Build the inference session. The processor handles
            # all preprocessing (frame resize / normalize / pixel_values
            # tensor allocation); we don't manually call
            # ``processor(images=...)`` anymore.
            inference_session = loaded.processor.init_video_session(
                video=frames_pil,
                inference_device=str(loaded.device),
                dtype=loaded.dtype,
            )

            # 4b. Add the anchor bbox. ``input_boxes`` is nested
            # 3-deep: outer batch (one video), middle per-object
            # (one bbox), innermost xyxy coords. ``original_size``
            # is required so the processor can scale the bbox from
            # frame-pixel space to the model's normalized internal
            # coordinates.
            loaded.processor.process_new_points_or_boxes_for_video_frame(
                inference_session=inference_session,
                frame_idx=anchor_idx,
                obj_ids=[1],
                input_boxes=[[[
                    float(clamped_bbox.x),
                    float(clamped_bbox.y),
                    float(clamped_bbox.x + clamped_bbox.width),
                    float(clamped_bbox.y + clamped_bbox.height),
                ]]],
                original_size=(frame_height, frame_width),
            )

            # 4c. Propagate. The iterator yields one
            # ``Sam2VideoSegmentationOutput`` per frame in
            # ascending frame order; ``output.pred_masks`` has
            # shape ``(batch_size, num_objects, H, W)``.
            #
            # ``start_frame_idx=anchor_idx`` is REQUIRED. Without
            # it the iterator raises ``ValueError: Cannot determine
            # the starting frame index; please specify it manually,
            # or run inference on a frame with inputs first.`` —
            # observed on every scene of staging incident 2026-05-04
            # parent_job_id af195a4a. The auto-detect path expects
            # the session to be primed via ``model.forward(...)``
            # first, but we use the explicit-start path because
            # we know the anchor placement.
            samples: list[TrackedSample] = []
            for prop_idx, output in enumerate(
                loaded.model.propagate_in_video_iterator(
                    inference_session=inference_session,
                    start_frame_idx=anchor_idx,
                )
            ):
                if prop_idx >= len(sampled_frames):
                    continue  # defensive — should never exceed
                frame_ts_ms, _ = sampled_frames[prop_idx]

                # We added exactly one object (obj_id=1), so the
                # first dim of ``pred_masks`` is "this video" and
                # the second is "this object".
                mask_t = output.pred_masks[0, 0]
                # Confidence: prefer iou_scores when SAM2 emits
                # them on the output object; otherwise fall back
                # to mean-of-mask. Conservative default; calibration
                # can tighten later.
                iou_attr = getattr(output, "iou_scores", None)
                if iou_attr is not None:
                    try:
                        mask_conf = float(iou_attr.flatten()[0].item())
                    except Exception:  # noqa: BLE001
                        mask_conf = float(mask_t.float().mean().item())
                else:
                    mask_conf = float(mask_t.float().mean().item())
                mask_np = mask_t.detach().cpu().numpy()
                bbox = _mask_to_bbox(mask_np)
                if bbox is None:
                    # Empty mask — SAM2 lost the object. Emit a
                    # low-confidence sample with the anchor bbox
                    # as a placeholder; the lib's window-assembly
                    # threshold filters drop it.
                    samples.append(TrackedSample(
                        frame_timestamp_ms=frame_ts_ms,
                        bbox=clamped_bbox,
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


def _clamp_bbox_to_frame(
    bbox: BBoxXYWH, *, frame_width: int, frame_height: int,
) -> BBoxXYWH | None:
    """Clamp a bbox so it sits entirely inside ``[0, frame_width) ×
    [0, frame_height)``. Returns the clamped bbox, or ``None`` when
    the bbox is fully outside the frame and clamping would yield a
    zero-area region.

    Conventions matching :class:`BBoxXYWH` (``width`` and ``height``
    are extents, not maxima):
      * ``bbox.x``, ``bbox.y`` are clamped to ``[0, frame_width-1]``
        and ``[0, frame_height-1]`` respectively.
      * ``bbox.x + bbox.width`` and ``bbox.y + bbox.height`` are
        clamped so the right/bottom edges fit.
      * If after clamping the resulting width or height is ``<= 0``,
        the bbox is effectively off-frame; return ``None`` so the
        caller can raise loudly.

    Required because the LLM enumeration step occasionally produces
    a bbox whose right or bottom edge overflows the proxy frame
    (observed 2026-05-04 on staging entry c9f7c69e —
    ``BBoxXYWH(220, 150, 250, 300)`` on a 406x720 proxy). Clamping
    keeps SAM2 productive on the salvageable area; the worker
    surfaces a warning so the enumeration data-quality issue stays
    visible.
    """
    if frame_width <= 0 or frame_height <= 0:
        return None

    # Convert to edge coordinates first, clamp each edge to the frame
    # independently, then reconstruct the (x, y, width, height) tuple.
    # This is correct in both directions (negative origin, overflow
    # origin, overflow extent) and avoids the sign-juggling pitfall
    # where adding a "leading_x" can fail to shave the width.
    x0 = bbox.x
    x1 = bbox.x + bbox.width  # exclusive right edge
    y0 = bbox.y
    y1 = bbox.y + bbox.height

    nx0 = max(0, min(x0, frame_width))
    nx1 = max(0, min(x1, frame_width))
    ny0 = max(0, min(y0, frame_height))
    ny1 = max(0, min(y1, frame_height))

    new_width = nx1 - nx0
    new_height = ny1 - ny0

    if new_width <= 0 or new_height <= 0:
        return None
    if (
        nx0 == bbox.x
        and ny0 == bbox.y
        and new_width == bbox.width
        and new_height == bbox.height
    ):
        # Already fits — return the original instance so callers
        # can use ``clamped_bbox == anchor_bbox`` to detect "no
        # clamping happened".
        return bbox
    return BBoxXYWH(x=nx0, y=ny0, width=new_width, height=new_height)
