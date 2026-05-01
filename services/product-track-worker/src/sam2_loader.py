"""SAM2 model loader (singleton).

Mirrors :mod:`heimdex_media_pipelines.siglip2.loader` — module-global
singleton, lock-guarded lazy init, heavy imports deferred to call
time so the module is import-light for tests.

Phase 3c-A SCAFFOLD: this is currently a placeholder. The real SAM2
integration (loading checkpoints, building the video predictor) lands
in Phase 3c-B once we pick the python package (Meta's official
``sam2``, HF transformers' ``Sam2Model``, or ultralytics) and run
calibration on staging goldens. Calling :func:`load_sam2` raises
``NotImplementedError`` for now — workers boot and dispatch jobs, but
SAM2 propagation fails fast with a clear error rather than silently
returning empty samples.

A test fixture / mock should patch :func:`load_sam2` and the
``Sam2Tracker`` impl so unit tests cover the orchestration without
real SAM2 in the loop. See ``tests/conftest.py``.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class LoadedSam2:
    """Container for the loaded SAM2 model + processor + device.
    Same shape as :class:`heimdex_media_pipelines.siglip2.loader.LoadedSiglip`
    so future migration to a shared base type is straightforward.
    """

    model: Any
    processor: Any
    device: Any
    dtype: Any
    model_id: str


_singleton: LoadedSam2 | None = None
_lock = threading.Lock()


def load_sam2(*, model_id: str = "facebook/sam2-hiera-base-plus") -> LoadedSam2:
    """Lazy singleton load. Raises ``NotImplementedError`` until the
    Phase 3c-B SAM2 integration ships.

    Tests should never reach this — they patch ``load_sam2`` to
    return a stub :class:`LoadedSam2` (or override the
    :class:`src.sam2_tracker.Sam2TrackerImpl` entirely)."""
    global _singleton
    with _lock:
        if _singleton is not None:
            return _singleton
        # ---- TODO Phase 3c-B ----
        # Replace the NotImplementedError with the real SAM2 loader.
        # Likely shape:
        #
        #   import torch
        #   from sam2.build_sam import build_sam2_video_predictor
        #   device = "cuda" if torch.cuda.is_available() else "cpu"
        #   model = build_sam2_video_predictor(model_id, device=device)
        #   _singleton = LoadedSam2(model=model, processor=..., device=device, ...)
        #   return _singleton
        #
        # Calibration on staging goldens decides the variant.
        raise NotImplementedError(
            "SAM2 loader is a Phase 3c-A scaffold stub. "
            "Real SAM2 integration ships in Phase 3c-B once the python "
            "package + checkpoint are calibrated on staging goldens. "
            "See sam2_loader.py for the planned shape."
        )


def reset_singleton() -> None:
    """Test helper. Resets the loaded singleton."""
    global _singleton
    _singleton = None


def set_singleton_for_testing(loaded: LoadedSam2) -> None:
    """Test helper. Inject a stub so :func:`load_sam2` returns it on
    next call without trying to actually load weights."""
    global _singleton
    _singleton = loaded
