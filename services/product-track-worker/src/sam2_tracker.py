"""Concrete :class:`heimdex_media_pipelines.product_track.Sam2Tracker`
implementation.

Phase 3c-A SCAFFOLD: stub that raises ``NotImplementedError``. Real
SAM2 integration lands in Phase 3c-B alongside the loader.

For tests + dispatcher orchestration coverage, the recommended
pattern is to inject a fake tracker via the lib's Protocol — see
``tests/test_track_io.py``.
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
    """Real SAM2 video predictor wrapper. Phase 3c-A stub.

    The real implementation will:
      1. Load the video segment (presigned S3 url) via cv2 / pyav
      2. Locate the anchor frame (nearest keyframe to canonical_keyframe)
      3. Initialize the SAM2 video predictor with ``anchor_bbox`` mask
      4. Propagate forward to scene end + backward to scene start
      5. Sample masks at ``sample_fps`` (default 5)
      6. Convert masks to bboxes; emit one TrackedSample per sample
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
        # ---- TODO Phase 3c-B ----
        # Real implementation goes here. Until then, fail fast so
        # operators see "SAM2 not implemented" in /fail callbacks
        # rather than silently empty windows. Tests inject a fake
        # tracker via the Protocol.
        raise NotImplementedError(
            f"Sam2TrackerImpl.track is a Phase 3c-A stub "
            f"(scene_id={scene_id}, model_id={self._model_id}). "
            f"Real SAM2 integration ships in Phase 3c-B."
        )
