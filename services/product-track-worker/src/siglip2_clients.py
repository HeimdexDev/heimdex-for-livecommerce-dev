"""Concrete implementations of the Phase 3a Protocol clients.

Wires the lib's pure-function pipeline (which expects Protocol-injected
embedder + OS retrieval + keyframe fetcher) to real implementations
backed by:

* :func:`heimdex_media_pipelines.siglip2.embed_pil_image` — already
  loaded singleton (warmed at boot in ``worker.py``)
* :class:`src.api_client.ApiClient.find_similar_scenes` — Phase 3b
  internal endpoint
* S3 download via :class:`heimdex_worker_sdk.s3.S3Client` for keyframes
  (drive-worker writes them; this worker just reads)

All three classes are lightweight wrappers — the heavy lifting is in
the api / siglip2 lib. Workers stay mock-friendly because the lib's
Protocols accept any object satisfying the interface.
"""

from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING
from uuid import UUID

from heimdex_media_pipelines.product_track.siglip2_retrieval import (
    CoarseCandidate,
)

if TYPE_CHECKING:  # pragma: no cover
    from PIL import Image

    from heimdex_worker_sdk.s3 import S3Client

    from src.api_client import ApiClient

logger = logging.getLogger(__name__)


class SiglipEmbedderImpl:
    """Concrete SigLIP2 embedder. Defers the heavy import to call
    time so the module is importable without ``torch`` /
    ``transformers`` (test contexts can stub the entire class)."""

    def embed(self, image: "Image.Image") -> list[float]:
        from heimdex_media_pipelines.siglip2 import embed_pil_image
        return embed_pil_image(image)


class CoarseRetrievalClientImpl:
    """Calls the Phase 3b ``/internal/videos/{file_id}/scenes-by-visual-similarity``
    endpoint. ``file_id`` and ``org_id`` are bound at construction time
    because the lib's Protocol signature only accepts ``video_id`` (the
    OS string id) at the call site — the http endpoint needs the
    DriveFile UUID, which the worker resolves from the job message.

    ``scene_id_to_timing`` is the worker's ``scene_id → (start_ms,
    end_ms)`` map built once per job from the
    ``scenes-with-keyframes`` response. We use it here to populate
    ``CoarseCandidate.start_ms`` / ``end_ms`` so the SAM2 pass can
    window-slice a single full-video proxy without an extra fetch.
    Scenes the OS coarse-similarity endpoint returns but the
    timing map doesn't know about (race with re-split, deletion,
    etc.) are dropped silently — the lib tolerates a sparse
    candidate set per its per-scene-failure-isolation contract.
    """

    def __init__(
        self,
        *,
        api: "ApiClient",
        file_id: UUID,
        org_id: UUID,
        scene_id_to_timing: dict[str, tuple[int, int]],
    ) -> None:
        self._api = api
        self._file_id = file_id
        self._org_id = org_id
        self._scene_id_to_timing = scene_id_to_timing

    def find_similar_scenes(
        self,
        *,
        query_vec: list[float],
        video_id: str,
        top_k: int,
        min_similarity: float,
    ) -> list[CoarseCandidate]:
        # The lib passes ``video_id`` (the OS string id) for symmetry
        # with the rest of the pipeline; we don't need it because the
        # endpoint is path-scoped to ``file_id`` already. Logged for
        # debug if it ever drifts.
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "coarse_retrieval_video_id_mismatch_check",
                extra={"lib_video_id": video_id, "worker_file_id": str(self._file_id)},
            )

        scenes = self._api.find_similar_scenes(
            file_id=self._file_id,
            org_id=self._org_id,
            query_vec=query_vec,
            top_k=top_k,
            min_similarity=min_similarity,
        )
        out: list[CoarseCandidate] = []
        for s in scenes:
            scene_id = str(s["scene_id"])
            timing = self._scene_id_to_timing.get(scene_id)
            if timing is None:
                # Scene known to OS but missing from the worker's
                # scenes-with-keyframes timing map. Drop with a debug
                # log — the lib's per-scene-failure isolation handles
                # the missing-candidate case downstream, and silently
                # missing rows here is preferable to a hard crash on
                # what's almost always a benign race.
                logger.debug(
                    "coarse_candidate_dropped_no_timing",
                    extra={"scene_id": scene_id, "file_id": str(self._file_id)},
                )
                continue
            start_ms, end_ms = timing
            out.append(
                CoarseCandidate(
                    scene_id=scene_id,
                    coarse_similarity=float(s.get("similarity", 0.0)),
                    start_ms=start_ms,
                    end_ms=end_ms,
                )
            )
        return out


class KeyframeFetcherImpl:
    """Downloads a scene's keyframe JPEG from S3 and returns it as a
    PIL image. Workers pre-fetch the per-scene keyframe S3 keys via
    the Phase 2.5a ``scenes-with-keyframes`` endpoint and pass the
    map to this fetcher's constructor; missing keys raise
    ``KeyError`` which the lib catches + skips (per
    siglip2_retrieval's failure-isolation contract)."""

    def __init__(
        self,
        *,
        s3: "S3Client",
        bucket: str,
        scene_id_to_s3_key: dict[str, str],
    ) -> None:
        self._s3 = s3
        self._bucket = bucket
        self._scene_id_to_s3_key = scene_id_to_s3_key

    def fetch_scene_keyframe(self, scene_id: str) -> "Image.Image":
        from PIL import Image

        s3_key = self._scene_id_to_s3_key.get(scene_id)
        if s3_key is None:
            # Per Phase 3a contract: lib catches Exception and skips
            # the scene. KeyError is the natural choice for "key not
            # in map".
            raise KeyError(f"keyframe S3 key not found for scene_id={scene_id}")

        # SDK contract: ``S3Client.get_object_bytes(s3_key)`` — bucket
        # is bound at construction; pass key positionally. Returns
        # ``None`` on NoSuchKey or transient errors (the SDK already
        # logged) — the lib's per-scene try/except would convert that
        # into a silent skip with no signal back to the worker, so we
        # raise here to surface the failure (and let the F4 counter
        # see it).
        body = self._s3.get_object_bytes(s3_key)
        if body is None:
            raise FileNotFoundError(
                f"S3 object missing for scene_id={scene_id} key={s3_key}"
            )
        return Image.open(io.BytesIO(body)).convert("RGB")
