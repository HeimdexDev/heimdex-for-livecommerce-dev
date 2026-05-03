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
    metadata.

    Tracks playback position so the tracker's ``cap.set(POS_MSEC)``
    seek + ``cap.get(POS_MSEC)`` window-trim logic can be exercised
    without a real video file. ``keyframe_interval_ms`` simulates
    the keyframe-aligned seek behaviour of real cv2 + H.264 — when
    set, ``set(POS_MSEC, t)`` snaps to the largest keyframe <= t,
    which is exactly the scenario the pre-roll-drop logic in
    ``Sam2TrackerImpl`` defends against.
    """

    def __init__(
        self,
        *,
        frames: list[np.ndarray],
        fps: float = 30.0,
        keyframe_interval_ms: int | None = None,
    ):
        self._frames = frames
        self._idx = 0
        self._fps = fps
        self._w = frames[0].shape[1] if frames else 0
        self._h = frames[0].shape[0] if frames else 0
        self._opened = bool(frames)
        self._keyframe_interval_ms = keyframe_interval_ms
        # Public so tests can assert against seek calls without
        # reaching for a MagicMock spy.
        self.set_calls: list[tuple[int, float]] = []

    def isOpened(self) -> bool:
        return self._opened

    def get(self, prop: int) -> float:
        import cv2
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            return float(self._w)
        if prop == cv2.CAP_PROP_FRAME_HEIGHT:
            return float(self._h)
        if prop == cv2.CAP_PROP_FPS:
            return self._fps
        if prop == cv2.CAP_PROP_FRAME_COUNT:
            return float(len(self._frames))
        if prop == cv2.CAP_PROP_POS_MSEC:
            # cv2 convention: time of the NEXT frame to be decoded.
            if self._fps <= 0:
                return 0.0
            return self._idx * 1000.0 / self._fps
        return 0.0

    def set(self, prop: int, value: float) -> bool:
        import cv2
        self.set_calls.append((prop, float(value)))
        if prop == cv2.CAP_PROP_POS_MSEC:
            target_ms = float(value)
            if self._keyframe_interval_ms is not None:
                # Snap to largest keyframe <= target — mirrors real
                # cv2 + H.264 with a finite GOP.
                kf = self._keyframe_interval_ms
                target_ms = (int(target_ms) // kf) * kf
            if self._fps <= 0:
                self._idx = 0
            else:
                self._idx = max(0, int(round(target_ms * self._fps / 1000.0)))
            return True
        return False

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
                    full_video_path="/nonexistent/proxy.mp4",
                    scene_start_ms=0,
                    scene_end_ms=1000,
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
                    full_video_path="/tmp/proxy.mp4",
                    scene_start_ms=0,
                    scene_end_ms=1000,
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
            with pytest.raises(RuntimeError, match="no frames decoded in scene window"):
                tracker.track(
                    scene_id="s1",
                    anchor_bbox=_bbox_for_320x240(),
                    anchor_keyframe=Image.new("RGB", (1, 1)),
                    full_video_path="/tmp/proxy.mp4",
                    scene_start_ms=0,
                    scene_end_ms=1000,
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
        # Source video: 30fps, 30 frames covering 0..966 ms. Scene
        # window 0..1000 ms; sample_fps=5 → 200 ms cadence → frames
        # accepted at timestamps 0, 200, 400, 600, 800.
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
                full_video_path="/tmp/proxy.mp4",
                scene_start_ms=0,
                scene_end_ms=1000,
                sample_fps=5,
            )

        assert len(samples) == 5
        timestamps = [s.frame_timestamp_ms for s in samples]
        assert timestamps == sorted(timestamps), "monotonic ascending order"
        # Sample boundaries at 0, 200, 400, 600, 800 ms hit frames at
        # the same exact timestamps (30fps lands cleanly).
        assert timestamps == [0, 200, 400, 600, 800]
        # Mask is 60x60 starting at (30, 20) per ``_make_fake_predictor``.
        assert all(s.bbox.width == 60 and s.bbox.height == 60 for s in samples)
        # Frame dimensions propagated through.
        assert all(s.frame_width == 320 and s.frame_height == 240 for s in samples)
        # Confidence taken from masks.score per-frame.
        assert all(0.9 < s.mask_confidence <= 1.0 for s in samples)


# =====================================================================
# Sam2TrackerImpl seek + scene-window behaviour (post-2026-05-04)
# =====================================================================


def _adaptive_predictor(*, mask_h: int = 240, mask_w: int = 320) -> MagicMock:
    """Like ``_make_fake_predictor`` but emits one sample per
    sampled frame regardless of count — the new tests below sample
    different numbers of frames depending on the scene window."""
    import torch

    def _make_mask():
        m = np.zeros((mask_h, mask_w), dtype=np.uint8)
        m[20:80, 30:90] = 1
        return torch.tensor(m)

    captured: dict = {}

    def _propagate(state):
        # Walk an arbitrary number of indices — the tracker stops
        # iterating once ``prop_idx >= len(sampled_frames)``.
        for prop_idx in range(captured.get("sample_count", 1000)):
            masks = MagicMock()
            masks.__getitem__.return_value = _make_mask()
            masks.score = 0.95
            yield prop_idx, [1], masks

    model = MagicMock()
    model.init_state.return_value = MagicMock()
    model.add_new_points_or_box.return_value = None
    model.propagate_in_video.side_effect = _propagate
    return model


class TestSam2TrackerImplSeekAndWindow:
    """Exercises the seek + per-scene window-trim logic added when
    SAM2 switched from per-scene mp4s to a single full-video proxy
    (handoff sam2-proxy-handoff-2026-05-04)."""

    def _build(self, *, frames, fps=30.0, keyframe_interval_ms=None):
        cap = _FakeVideoCapture(
            frames=frames, fps=fps, keyframe_interval_ms=keyframe_interval_ms,
        )
        model = _adaptive_predictor()
        processor = MagicMock()
        processor.return_value.to.return_value = {"pixel_values": MagicMock()}
        set_singleton_for_testing(_fake_loaded(model, processor=processor))
        return cap, Sam2TrackerImpl(model_id="x")

    def test_seek_called_once_with_scene_start_ms(self):
        """Tracker MUST call ``cap.set(CAP_PROP_POS_MSEC, scene_start_ms)``
        exactly once before reading any frames. Locks the contract
        so a future refactor that "optimizes away" the seek for
        scene_start_ms=0 doesn't silently regress non-zero windows."""
        import cv2
        cap, tracker = self._build(frames=[_green_frame() for _ in range(60)])

        with patch("cv2.VideoCapture", return_value=cap):
            tracker.track(
                scene_id="s1",
                anchor_bbox=_bbox_for_320x240(),
                anchor_keyframe=Image.new("RGB", (1, 1)),
                full_video_path="/tmp/proxy.mp4",
                scene_start_ms=400,
                scene_end_ms=1000,
                sample_fps=5,
            )

        seek_calls = [
            (prop, val) for prop, val in cap.set_calls
            if prop == cv2.CAP_PROP_POS_MSEC
        ]
        assert seek_calls == [(cv2.CAP_PROP_POS_MSEC, 400.0)], (
            f"expected exactly one POS_MSEC seek to 400.0, got {seek_calls}"
        )

    def test_pre_roll_frames_dropped_when_seek_keyframe_aligned(self):
        """Real cv2 + H.264 seeks to the keyframe BEFORE the
        requested ms (every 2s GOP here). The tracker must drop
        those pre-roll frames so SAM2 only sees frames inside the
        candidate window. Without this, scene-boundary detection
        would be polluted by frames from the PRECEDING scene."""
        # 6s video at 30fps = 180 frames; keyframes every 2000ms.
        frames = [_green_frame() for _ in range(180)]
        cap, tracker = self._build(
            frames=frames, fps=30.0, keyframe_interval_ms=2000,
        )

        with patch("cv2.VideoCapture", return_value=cap):
            samples = tracker.track(
                scene_id="s1",
                anchor_bbox=_bbox_for_320x240(),
                anchor_keyframe=Image.new("RGB", (1, 1)),
                full_video_path="/tmp/proxy.mp4",
                # Seek to 5000 ms snaps to keyframe at 4000 ms.
                # Frames 4000..4966 are pre-roll — must NOT appear
                # in samples.
                scene_start_ms=5000,
                scene_end_ms=6000,
                sample_fps=5,
            )

        assert len(samples) > 0, "should have emitted at least one in-window sample"
        for s in samples:
            assert s.frame_timestamp_ms >= 5000, (
                f"pre-roll frame leaked: ts={s.frame_timestamp_ms} < scene_start=5000"
            )
            assert s.frame_timestamp_ms <= 6000, (
                f"post-window frame leaked: ts={s.frame_timestamp_ms} > scene_end=6000"
            )

    def test_loop_stops_at_scene_end_ms(self):
        """Decoding the whole proxy when only a scene's worth of
        frames is needed wastes 10x+ on a typical livecommerce
        video. The loop must break the moment ``pos_ms >
        scene_end_ms``, not just filter."""
        # 4s of video (120 frames at 30fps). Window only covers
        # the first second.
        frames = [_green_frame() for _ in range(120)]
        cap, tracker = self._build(frames=frames, fps=30.0)

        with patch("cv2.VideoCapture", return_value=cap):
            samples = tracker.track(
                scene_id="s1",
                anchor_bbox=_bbox_for_320x240(),
                anchor_keyframe=Image.new("RGB", (1, 1)),
                full_video_path="/tmp/proxy.mp4",
                scene_start_ms=0,
                scene_end_ms=1000,
                sample_fps=5,
            )

        # No sample exceeds the scene end — strong signal that the
        # loop stopped, not just filtered.
        assert all(s.frame_timestamp_ms <= 1000 for s in samples)
        # Cap stopped reading shortly after 1000 ms — index advanced
        # to ~31 (frame at 1033 ms triggered the break), not 120.
        assert cap._idx <= 35, (
            f"loop kept decoding past the window: read {cap._idx} of 120 frames"
        )
