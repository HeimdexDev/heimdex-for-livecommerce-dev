import os
from typing import Iterable, List, Optional

import cv2


def _video_duration_s(video_path: str) -> float:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 0.0
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
    cap.release()
    if fps <= 0.0 or frame_count <= 0.0:
        return 0.0
    return float(frame_count) / float(fps)


def _dedupe_sorted(values: Iterable[float], ndigits: int = 3) -> List[float]:
    seen = set()
    result: List[float] = []
    for value in sorted(values):
        key = round(value, ndigits)
        if key in seen:
            continue
        seen.add(key)
        result.append(float(key))
    return result


def sample_timestamps(
    video_path: str,
    fps: float = 1.0,
    scene_boundaries_s: Optional[Iterable[float]] = None,
    boundary_window_s: float = 0.5,
) -> List[float]:
    """Return a list of timestamps (seconds) sampled at the desired fps.

    If scene boundaries are provided, add extra samples around each boundary.
    """
    if fps <= 0:
        raise ValueError("fps must be > 0")
    if not os.path.exists(video_path):
        raise FileNotFoundError(video_path)

    duration_s = _video_duration_s(video_path)

    if not duration_s or duration_s <= 0:
        return []

    step = 1.0 / fps
    timestamps = []
    t = 0.0
    while t <= duration_s:
        timestamps.append(t)
        t += step

    if scene_boundaries_s:
        offsets = [-boundary_window_s, -boundary_window_s / 2, 0.0, boundary_window_s / 2, boundary_window_s]
        for boundary in scene_boundaries_s:
            for offset in offsets:
                ts = boundary + offset
                if 0.0 <= ts <= duration_s:
                    timestamps.append(ts)

    return _dedupe_sorted(timestamps)
