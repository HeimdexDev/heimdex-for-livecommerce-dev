"""SAM2 model loader (singleton).

Mirrors :mod:`heimdex_media_pipelines.siglip2.loader` — module-global
singleton, lock-guarded lazy init, heavy imports deferred to call
time so the module is import-light for tests.

Phase 3c-B: real implementation using HuggingFace transformers'
``Sam2VideoModel`` + ``Sam2VideoProcessor`` (calibration default —
the handoff-doc-allowed alternatives are Meta's official ``sam2``
package or ultralytics; transformers wins on ecosystem fit since
SigLIP2 is already there).

Calibration on staging goldens locks the variant. ``base-plus`` is
the starting point per plan §6.2 — if mean window IoU falls short
of 0.6, swap to ``hiera-large`` (one-line config bump in
``WorkerSettings.sam2_model_id``) or fall back to DINOv2 entirely
per plan calibration gate.

Tests inject a fake :class:`LoadedSam2` via
:func:`set_singleton_for_testing` so :func:`load_sam2` returns the
fake without trying to download weights / move tensors to CUDA.
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
    ``model`` is a :class:`transformers.Sam2VideoModel` (or
    :class:`Sam2Model` for image-only — track worker uses video).
    """

    model: Any
    processor: Any
    device: Any
    dtype: Any
    model_id: str


_singleton: LoadedSam2 | None = None
_lock = threading.Lock()


def load_sam2(*, model_id: str = "facebook/sam2-hiera-base-plus") -> LoadedSam2:
    """Lazy singleton load of the HF transformers SAM2 video model.

    Boot-time path:

      1. Import torch + transformers lazily (module-import is
         intentionally light so tests don't pay the cost).
      2. Pick device: CUDA when available, fallback CPU is
         developer-only — the worker's boot guard refuses CPU mode
         in prod via ``WorkerSettings.track_allow_cpu``.
      3. Pick dtype: ``float16`` on GPU (halves memory + matches
         drive-visual-embed-worker's SigLIP2 dtype convention),
         ``float32`` on CPU.
      4. Load model + processor via ``from_pretrained``. The HF
         cache lives at ``HF_HOME=/models/hf`` (set in
         Dockerfile.gpu); weights are pre-warmed at build time.
      5. Move model to device, set eval mode, store the singleton.

    Concurrency: the lock prevents double-load if two boot threads
    race; the second blocks until the first finishes.
    """
    global _singleton
    with _lock:
        if _singleton is not None:
            return _singleton

        import torch
        # Lazy import: ``Sam2VideoModel`` was added to the
        # transformers library in v4.48; we pin a newer version in
        # requirements.txt. The video model has the propagation API
        # (``init_state`` / ``add_new_points_or_box`` /
        # ``propagate_in_video``) the tracker needs. Image-only
        # ``Sam2Model`` would force per-frame inference which is
        # both slower and produces noisier tracks across cuts.
        from transformers import Sam2VideoModel, Sam2VideoProcessor

        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if device == "cuda" else torch.float32

        logger.info(
            "sam2_load_starting",
            extra={"model_id": model_id, "device": device, "dtype": str(dtype)},
        )
        model = Sam2VideoModel.from_pretrained(
            model_id, torch_dtype=dtype,
        ).to(device).eval()
        processor = Sam2VideoProcessor.from_pretrained(model_id)

        _singleton = LoadedSam2(
            model=model,
            processor=processor,
            device=device,
            dtype=dtype,
            model_id=model_id,
        )
        logger.info("sam2_load_complete", extra={"model_id": model_id})
        return _singleton


def reset_singleton() -> None:
    """Test helper. Resets the loaded singleton."""
    global _singleton
    _singleton = None


def set_singleton_for_testing(loaded: LoadedSam2) -> None:
    """Test helper. Inject a stub so :func:`load_sam2` returns it on
    next call without trying to actually load weights."""
    global _singleton
    _singleton = loaded
