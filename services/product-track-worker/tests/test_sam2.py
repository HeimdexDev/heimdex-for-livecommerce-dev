"""Phase 3c-B Item 4 — SAM2 loader + tracker tests.

The HF transformers ``Sam2VideoModel`` API is volatile across
versions and requires real GPU weights to validate inference. We
test the structural surface here:

  * ``load_sam2`` singleton semantics + ``set_singleton_for_testing``
    injection.
  * ``Sam2TrackerImpl.track`` flow against a fake video predictor +
    a mocked ``cv2.VideoCapture``: anchor bounds check, frame
    sampling at ``sample_fps``, mask → bbox conversion, monotonic
    output ordering, runtime errors on bad inputs.
  * ``_mask_to_bbox`` helper: pure function, broad coverage.

Real-GPU validation deferred to Phase 3d staging soak.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image

from heimdex_media_pipelines.product_track.sam2_pass import BBoxXYWH

from src.sam2_loader import (
    LoadedSam2,
    load_sam2,
    reset_singleton,
    set_singleton_for_testing,
)
from src.sam2_tracker import Sam2TrackerImpl, _mask_to_bbox


@pytest.fixture(autouse=True)
def _reset_sam2_singleton():
    """Each test starts with no cached singleton so tests don't
    leak into each other (the loader caches forever otherwise)."""
    reset_singleton()
    yield
    reset_singleton()


def _fake_loaded(model: Any, processor: Any | None = None) -> LoadedSam2:
    return LoadedSam2(
        model=model,
        processor=processor or MagicMock(),
        device="cpu",
        dtype="float32",
        model_id="facebook/sam2-hiera-base-plus",
    )


# =====================================================================
# load_sam2 — singleton + injection point
# =====================================================================


class TestLoadSam2:
    def test_set_singleton_for_testing_returns_injected_value(self):
        """``set_singleton_for_testing`` short-circuits the real
        load path so tests don't pay the transformers + CUDA cost.
        Pinned because every Sam2TrackerImpl test depends on this
        injection working — drift here would explode every track
        test on a fresh runner without GPU."""
        fake_model = MagicMock()
        injected = _fake_loaded(fake_model)
        set_singleton_for_testing(injected)
        out = load_sam2()
        assert out is injected
        assert out.model is fake_model

    def test_load_sam2_caches_singleton_across_calls(self):
        """Once loaded, subsequent calls return the SAME instance —
        no re-load. (We verify via the injection point because a
        real load needs GPU.)"""
        injected = _fake_loaded(MagicMock())
        set_singleton_for_testing(injected)
        a = load_sam2()
        b = load_sam2(model_id="some-other-id")  # arg ignored once loaded
        assert a is b


# =====================================================================
# _mask_to_bbox — pure function
# =====================================================================


class TestMaskToBbox:
    def test_returns_tight_bbox_for_filled_region(self):
        # 10x10 mask with a 4x6 rectangle of foreground.
        mask = np.zeros((10, 10), dtype=bool)
        mask[2:8, 3:7] = True
        bbox = _mask_to_bbox(mask)
        assert bbox == BBoxXYWH(x=3, y=2, width=4, height=6)

    def test_returns_none_for_empty_mask(self):
        assert _mask_to_bbox(np.zeros((10, 10), dtype=bool)) is None

    def test_handles_uint8_mask(self):
        mask = np.zeros((5, 5), dtype=np.uint8)
        mask[1, 1] = 255
        bbox = _mask_to_bbox(mask)
        assert bbox == BBoxXYWH(x=1, y=1, width=1, height=1)


# =====================================================================
# Sam2TrackerImpl.track
# =====================================================================


class _FakeVideoCapture:
    """Mimics cv2.VideoCapture for tests — returns a programmable
    sequence of (ok, frame) pairs and reports configurable
    metadata."""

    def __init__(self, *, frames: list[np.ndarray], fps: float = 30.0):
        self._frames = frames
        self._idx = 0
        self._fps = fps
        self._w = frames[0].shape[1] if frames else 0
        self._h = frames[0].shape[0] if frames else 0
        self._opened = bool(frames)

    def isOpened(self) -> bool:
        return self._opened

    def get(self, prop: int) -> float:
        # Mirror the cv2 prop ids the tracker queries.
        import cv2
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            return float(self._w)
        if prop == cv2.CAP_PROP_FRAME_HEIGHT:
            return float(self._h)
        if prop == cv2.CAP_PROP_FPS:
            return self._fps
        if prop == cv2.CAP_PROP_FRAME_COUNT:
            return float(len(self._frames))
        return 0.0

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self._idx >= len(self._frames):
            return False, None
        frame = self._frames[self._idx]
        self._idx += 1
        return True, frame

    def release(self) -> None:
        self._opened = False


def _green_frame(*, w: int = 320, h: int = 240) -> np.ndarray:
    """An RGB frame the tracker will pass through cv2.cvtColor; we
    use BGR ordering since cv2.VideoCapture would output BGR."""
    bgr = np.zeros((h, w, 3), dtype=np.uint8)
    bgr[:, :, 1] = 200  # green channel
    return bgr


def _bbox_for_320x240() -> BBoxXYWH:
    return BBoxXYWH(x=10, y=10, width=50, height=50)


class TestSam2TrackerImplFailureModes:
    def test_raises_runtime_when_video_open_fails(self):
        """The lib's per-scene try/except marks this scene as
        failed; the F4 ``_CountingSam2Tracker`` then catches the
        all-scenes-failed case if every track call hits this
        path."""
        tracker = Sam2TrackerImpl(model_id="x")
        set_singleton_for_testing(_fake_loaded(MagicMock()))
        with patch("cv2.VideoCapture") as cap_factory:
            cap_factory.return_value = _FakeVideoCapture(frames=[])
            with pytest.raises(RuntimeError, match="failed to open"):
                tracker.track(
                    scene_id="s1",
                    anchor_bbox=_bbox_for_320x240(),
                    anchor_keyframe=Image.new("RGB", (1, 1)),
                    scene_video_url="bad://url",
                    sample_fps=5,
                )

    def test_raises_value_error_when_anchor_bbox_outside_frame(self):
        """Anchor bbox out-of-bounds means SAM2 would happily run
        but produce nonsense masks — surface the misconfiguration
        loudly at the worker boundary."""
        tracker = Sam2TrackerImpl(model_id="x")
        set_singleton_for_testing(_fake_loaded(MagicMock()))
        frames = [_green_frame() for _ in range(5)]
        bad_bbox = BBoxXYWH(x=10, y=10, width=500, height=500)  # > 320x240
        with patch("cv2.VideoCapture") as cap_factory:
            cap_factory.return_value = _FakeVideoCapture(frames=frames)
            with pytest.raises(ValueError, match="anchor_bbox"):
                tracker.track(
                    scene_id="s1",
                    anchor_bbox=bad_bbox,
                    anchor_keyframe=Image.new("RGB", (1, 1)),
                    scene_video_url="x",
                    sample_fps=5,
                )

    def test_raises_runtime_when_no_frames_decoded(self):
        """Capture opens but yields zero frames (corrupted proxy /
        zero-byte file). Stage-wide-failure if every scene hits
        this; per-scene if it's just one bad upload."""
        tracker = Sam2TrackerImpl(model_id="x")
        set_singleton_for_testing(_fake_loaded(MagicMock()))
        # ``isOpened`` returns True but ``read`` returns (False, None)
        # immediately. _FakeVideoCapture's open semantics need a hack
        # for this case: we mark opened by hand.
        cap = _FakeVideoCapture(frames=[])
        cap._opened = True  # noqa: SLF001
        with patch("cv2.VideoCapture", return_value=cap):
            with pytest.raises(RuntimeError, match="no frames decoded"):
                tracker.track(
                    scene_id="s1",
                    anchor_bbox=_bbox_for_320x240(),
                    anchor_keyframe=Image.new("RGB", (1, 1)),
                    scene_video_url="x",
                    sample_fps=5,
                )


class TestSam2TrackerImplHappyPath:
    def _make_fake_predictor(
        self, *, mask_h: int = 240, mask_w: int = 320,
    ) -> MagicMock:
        """Produces a model whose ``propagate_in_video`` yields
        increasing-time samples with a small bbox-sized mask
        (so ``_mask_to_bbox`` returns a valid bbox)."""
        import torch

        def _make_mask():
            m = np.zeros((mask_h, mask_w), dtype=np.uint8)
            m[20:80, 30:90] = 1
            return torch.tensor(m)

        def _propagate(_state):
            for prop_idx in range(5):  # 5 sampled frames
                masks = MagicMock()
                masks.__getitem__.return_value = _make_mask()
                masks.score = 0.95
                yield prop_idx, [1], masks

        model = MagicMock()
        model.init_state.return_value = MagicMock()
        model.add_new_points_or_box.return_value = None
        model.propagate_in_video.side_effect = _propagate
        return model

    def test_emits_one_sample_per_propagated_frame_in_time_order(self):
        """5 propagated frames → 5 ``TrackedSample`` rows in
        monotonic ``frame_timestamp_ms`` order; each carries the
        bbox ``_mask_to_bbox`` derives from the predictor's mask."""
        # Source video: 30fps, 30 frames total; sample_fps=5 →
        # stride=6 → 5 sampled frames at indexes [0, 6, 12, 18, 24].
        frames = [_green_frame() for _ in range(30)]
        cap = _FakeVideoCapture(frames=frames, fps=30.0)
        model = self._make_fake_predictor()
        processor = MagicMock()
        processor.return_value.to.return_value = {
            "pixel_values": MagicMock(),
        }
        set_singleton_for_testing(_fake_loaded(model, processor=processor))
        tracker = Sam2TrackerImpl(model_id="x")

        with patch("cv2.VideoCapture", return_value=cap):
            samples = tracker.track(
                scene_id="s1",
                anchor_bbox=_bbox_for_320x240(),
                anchor_keyframe=Image.new("RGB", (1, 1)),
                scene_video_url="x",
                sample_fps=5,
            )

        assert len(samples) == 5
        timestamps = [s.frame_timestamp_ms for s in samples]
        assert timestamps == sorted(timestamps), "monotonic ascending order"
        # Frame indexes 0, 6, 12, 18, 24 at 30fps → 0, 200, 400, 600, 800ms.
        assert timestamps == [0, 200, 400, 600, 800]
        # Mask is 60x60 starting at (30, 20) per ``_make_fake_predictor``.
        assert all(s.bbox.width == 60 and s.bbox.height == 60 for s in samples)
        # Frame dimensions propagated through.
        assert all(s.frame_width == 320 and s.frame_height == 240 for s in samples)
        # Confidence taken from masks.score per-frame.
        assert all(0.9 < s.mask_confidence <= 1.0 for s in samples)
