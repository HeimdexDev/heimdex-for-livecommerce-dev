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

    def test_raises_value_error_when_anchor_bbox_fully_off_frame(self):
        """A bbox whose origin is past the frame edge (or whose
        width/height clamp to ≤ 0) is genuinely unsalvageable —
        SAM2 has no anchor area. Surface as a ValueError so the
        lib's per-scene catch logs it. Bboxes that merely overflow
        the right/bottom edge get clamped instead (see
        ``test_anchor_bbox_overflowing_frame_is_clamped``)."""
        tracker = Sam2TrackerImpl(model_id="x")
        set_singleton_for_testing(_fake_loaded(MagicMock()))
        frames = [_green_frame() for _ in range(5)]
        # Origin at (1000, 1000) with width=1 → after clamp to a 320x240
        # frame the new x snaps to 319, leading_x = 319-1000 = -681,
        # so new_width = 1 + (-681) = -680 → clamp returns None → raise.
        bad_bbox = BBoxXYWH(x=1000, y=1000, width=1, height=1)
        with patch("cv2.VideoCapture") as cap_factory:
            cap_factory.return_value = _FakeVideoCapture(frames=frames)
            with pytest.raises(ValueError, match="falls entirely outside frame"):
                tracker.track(
                    scene_id="s1",
                    anchor_bbox=bad_bbox,
                    anchor_keyframe=Image.new("RGB", (1, 1)),
                    full_video_path="/tmp/proxy.mp4",
                    scene_start_ms=0,
                    scene_end_ms=1000,
                    sample_fps=5,
                )

    def test_anchor_bbox_overflowing_frame_is_clamped(self):
        """The 2026-05-04 staging incident (catalog c9f7c69e) failed
        every scene because the LLM enumeration produced
        ``BBoxXYWH(220, 150, 250, 300)`` whose ``x + width = 470``
        exceeded the proxy width 406 by 64 px. Strict rejection
        F4'd every product. Clamping is the right default — SAM2
        gets a usable anchor on the salvageable area, and the
        operator sees a warning so the enumeration data quality
        issue is still visible.

        Pin the contract: bbox overflow on the right/bottom edge
        does NOT raise; it gets clamped to the frame and tracking
        proceeds."""
        # Source video: 30fps, 30 frames; sample_fps=5 → 5 samples
        # in [0, 1000ms]. Mirror the
        # ``test_emits_one_sample_per_propagated_frame_in_time_order``
        # setup so we know we hit the SAM2 path (not the
        # no-frames-decoded fail).
        frames = [_green_frame() for _ in range(30)]
        cap = _FakeVideoCapture(frames=frames, fps=30.0)
        # Real-incident bbox shape: starts inside frame, exceeds
        # right edge by 64 px. Frame is 320x240 here so we use the
        # equivalent overflow ratio.
        overflow_bbox = BBoxXYWH(x=200, y=100, width=200, height=100)
        # x + w = 400 > frame_width 320 → clamp width to 320-200=120.

        # Capture the box passed into add_new_points_or_box so we
        # can verify it was clamped, not raised.
        captured: dict = {}

        class _CapturingPredictor:
            def init_state(self, *, pixel_values):
                return MagicMock()

            def add_new_points_or_box(self, *, state, frame_idx, obj_id, box):
                captured["box"] = box

            def propagate_in_video(self, _state):
                return iter(())  # yield nothing — sampled list empty
                # is fine; outer code emits empty samples list which
                # the lib's downstream filter drops gracefully.

        processor = MagicMock()
        processor.return_value.to.return_value = {"pixel_values": MagicMock()}
        set_singleton_for_testing(_fake_loaded(_CapturingPredictor(), processor=processor))
        tracker = Sam2TrackerImpl(model_id="x")

        with patch("cv2.VideoCapture", return_value=cap):
            samples = tracker.track(
                scene_id="s1",
                anchor_bbox=overflow_bbox,
                anchor_keyframe=Image.new("RGB", (1, 1)),
                full_video_path="/tmp/proxy.mp4",
                scene_start_ms=0,
                scene_end_ms=1000,
                sample_fps=5,
            )

        # Did NOT raise. Empty samples are fine here; what matters
        # is that the box reaching SAM2 was clamped to the frame.
        assert isinstance(samples, list)
        assert "box" in captured, "SAM2 add_new_points_or_box never called"
        # Box format is [x_min, y_min, x_max, y_max]. Clamped width
        # is 320 - 200 = 120, so x_max = 200 + 120 = 320.
        assert captured["box"] == [200, 100, 320, 200], (
            f"expected clamped box [200, 100, 320, 200], got {captured['box']}"
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


# =====================================================================
# Sam2VideoProcessor input-format contract (PR E)
# =====================================================================


class TestSam2ProcessorInputShape:
    """The 2026-05-04 staging incident (parent_job_id dfc2c05b) hit
    ``ValueError: Either images or original_sizes must be provided``
    on every one of 11 scenes. Root cause: we were passing
    ``videos=frames_np`` (a stacked 4D ndarray) to
    ``Sam2VideoProcessor``; transformers expects a list-of-lists
    with PIL images.

    Tests pin the call-shape contract so this regression class is
    caught in CI."""

    def _build_capturing_processor(self) -> tuple:
        captured: dict = {}

        class _CapturingProcessor:
            def __call__(self, *args, **kwargs):
                captured["args"] = args
                captured["kwargs"] = kwargs
                # Mimic the real return_tensors="pt" + .to(device) chain.
                resp = MagicMock()
                resp.to.return_value = {"pixel_values": MagicMock()}
                return resp

        return _CapturingProcessor(), captured

    def test_processor_receives_videos_as_list_of_lists_of_pil_images(self):
        """``Sam2VideoProcessor`` requires
        ``videos: List[List[ImageInput]]`` — outer list is one entry
        per video, inner list is the frames. Pin both shapes so a
        regression here surfaces in CI rather than at SAM2 call
        time on Aircloud (which is what bit us 2026-05-04)."""
        from PIL import Image as _PIL

        frames = [_green_frame() for _ in range(30)]
        cap = _FakeVideoCapture(frames=frames, fps=30.0)
        proc, captured = self._build_capturing_processor()
        model = MagicMock()
        model.init_state.return_value = MagicMock()
        model.add_new_points_or_box.return_value = None
        model.propagate_in_video.side_effect = lambda _state: iter(())
        set_singleton_for_testing(_fake_loaded(model, processor=proc))
        tracker = Sam2TrackerImpl(model_id="x")

        with patch("cv2.VideoCapture", return_value=cap):
            tracker.track(
                scene_id="s1",
                anchor_bbox=_bbox_for_320x240(),
                anchor_keyframe=_PIL.new("RGB", (1, 1)),
                full_video_path="/tmp/proxy.mp4",
                scene_start_ms=0,
                scene_end_ms=1000,
                sample_fps=5,
            )

        videos = captured["kwargs"].get("videos")
        assert videos is not None, (
            f"processor not called with ``videos=`` kwarg; got "
            f"kwargs={list(captured['kwargs'].keys())}"
        )
        # Outer: list with exactly one entry (single video).
        assert isinstance(videos, list), f"videos must be a list; got {type(videos)}"
        assert len(videos) == 1, f"expected 1 video; got {len(videos)}"
        # Inner: list of PIL images, NOT a stacked ndarray.
        inner = videos[0]
        assert isinstance(inner, list), (
            f"inner ``videos[0]`` must be a list of frames, not "
            f"{type(inner).__name__} — passing a stacked ndarray "
            f"falls through to ``Either images or original_sizes "
            f"must be provided``"
        )
        assert all(isinstance(f, _PIL.Image) for f in inner), (
            "all inner items must be PIL images"
        )
        assert len(inner) == 5, (
            f"expected 5 sampled frames at 30fps/sample_fps=5/1000ms window; "
            f"got {len(inner)}"
        )


# =====================================================================
# _clamp_bbox_to_frame — pure function (PR E)
# =====================================================================


class TestClampBboxToFrame:
    """Broad coverage of the clamping helper. Independent of cv2
    so this runs even on hosts without opencv-python-headless."""

    def test_returns_bbox_unchanged_when_already_inside_frame(self):
        from src.sam2_tracker import _clamp_bbox_to_frame

        bbox = BBoxXYWH(x=10, y=20, width=100, height=50)
        out = _clamp_bbox_to_frame(bbox, frame_width=200, frame_height=200)
        assert out == bbox

    def test_clamps_right_edge_overflow(self):
        from src.sam2_tracker import _clamp_bbox_to_frame

        # Mirrors the real-incident shape (catalog c9f7c69e).
        bbox = BBoxXYWH(x=220, y=150, width=250, height=300)
        out = _clamp_bbox_to_frame(bbox, frame_width=406, frame_height=720)
        assert out is not None
        assert out.x == 220
        assert out.y == 150
        # 406 - 220 = 186 (the salvageable width)
        assert out.width == 186
        assert out.height == 300  # bottom edge fits

    def test_clamps_bottom_edge_overflow(self):
        from src.sam2_tracker import _clamp_bbox_to_frame

        bbox = BBoxXYWH(x=10, y=200, width=50, height=100)
        out = _clamp_bbox_to_frame(bbox, frame_width=320, frame_height=240)
        assert out is not None
        assert out.height == 240 - 200  # 40 px

    def test_clamps_negative_origin(self):
        from src.sam2_tracker import _clamp_bbox_to_frame

        bbox = BBoxXYWH(x=-20, y=-10, width=100, height=80)
        out = _clamp_bbox_to_frame(bbox, frame_width=200, frame_height=200)
        assert out is not None
        # x snaps to 0; the leading 20px gets shaved off the width.
        assert out.x == 0
        assert out.y == 0
        assert out.width == 80   # original 100 minus 20 leading clamp
        assert out.height == 70  # original 80 minus 10 leading clamp

    def test_returns_none_when_origin_past_right_edge(self):
        from src.sam2_tracker import _clamp_bbox_to_frame

        bbox = BBoxXYWH(x=1000, y=10, width=50, height=50)
        out = _clamp_bbox_to_frame(bbox, frame_width=200, frame_height=200)
        assert out is None

    def test_returns_none_when_origin_past_bottom_edge(self):
        from src.sam2_tracker import _clamp_bbox_to_frame

        bbox = BBoxXYWH(x=10, y=1000, width=50, height=50)
        out = _clamp_bbox_to_frame(bbox, frame_width=200, frame_height=200)
        assert out is None

    def test_returns_none_for_zero_frame_dimensions(self):
        """Defensive: a 0x0 frame can't anchor any bbox."""
        from src.sam2_tracker import _clamp_bbox_to_frame

        bbox = BBoxXYWH(x=10, y=10, width=10, height=10)
        out = _clamp_bbox_to_frame(bbox, frame_width=0, frame_height=240)
        assert out is None
        out = _clamp_bbox_to_frame(bbox, frame_width=320, frame_height=0)
        assert out is None
