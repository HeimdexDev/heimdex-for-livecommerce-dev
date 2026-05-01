"""Per-job handler for ``product.track_job`` messages.

Orchestrates the Phase 3a pipeline lib's individual functions
(rather than ``run_tracking_pipeline``) so transcripts + OCR can
be fetched ONLY for the candidate scenes after retrieval — avoids
a wasteful pre-fetch of all scene transcripts up front.

Flow (per plan §6.2):

    1. Claim the job → API marks ``stage=tracking``, returns
       ``(org_id, video_id, catalog_entry_id, duration_preset_sec)``.
    2. Heartbeat ``progress_pct=10`` while we resolve the catalog
       entry + scene metadata.
    3. Fetch the canonical product crop from S3.
    4. Heartbeat ``progress_pct=20`` while we run SigLIP2 retrieval.
    5. Run :func:`retrieve_candidate_scenes` (coarse OS pre-filter +
       precise local re-embed) → candidate scene list.
    6. Heartbeat ``progress_pct=40`` while we propagate SAM2 over
       candidate scenes.
    7. Run :func:`propagate_within_candidate_scenes`.
    8. Run :func:`assemble_windows`.
    9. Fetch transcripts + OCR for accepted scenes only.
    10. Run :func:`annotate_alignment`.
    11. Heartbeat ``progress_pct=80`` while we score + pick.
    12. Run :func:`score_windows` + :func:`select_subset`.
    13. If selected is empty: complete the job with no stitch plan
        (UI surfaces "no qualifying appearances").
    14. Otherwise: build stitch plan, enqueue render via the api,
        complete the job with render_job_id.

Failures bubble up to the dispatcher boundary; this module raises
so the dispatcher maps to the right ``error_code`` on /fail.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

import httpx
# The lib's __init__ doesn't re-export — import each symbol from
# its submodule. Mirrors how product-enumerate-worker imports the
# product_enum lib.
from heimdex_media_pipelines.product_track.alignment import (
    OcrSegment,
    TranscriptSegment,
    annotate_alignment,
)
from heimdex_media_pipelines.product_track.config import TrackingConfig
from heimdex_media_pipelines.product_track.sam2_pass import (
    BBoxXYWH,
    Sam2Tracker,
    propagate_within_candidate_scenes,
)
from heimdex_media_pipelines.product_track.siglip2_retrieval import (
    SiglipEmbedder,
    retrieve_candidate_scenes,
)
from heimdex_media_pipelines.product_track.stitching import (
    build_stitch_plan,
)
from heimdex_media_pipelines.product_track.subset_selector import (
    ScoredWindow,
    SubsetPicker,
    score_windows,
    select_subset,
)
from heimdex_media_pipelines.product_track.window_assembly import (
    assemble_windows,
)
from heimdex_worker_sdk.s3 import S3Client

from src.api_client import ApiClient
from src.openai_picker import OpenAIPicker
from src.sam2_tracker import Sam2TrackerImpl
from src.settings import WorkerSettings
from src.siglip2_clients import (
    CoarseRetrievalClientImpl,
    KeyframeFetcherImpl,
    SiglipEmbedderImpl,
)

if TYPE_CHECKING:  # pragma: no cover
    from PIL import Image

logger = logging.getLogger(__name__)


# ─── F4 stage-failure counters ──────────────────────────────────────
#
# The Phase 3a pipeline lib tolerates per-scene errors (keyframe fetch,
# embed, SAM2 track) and silently continues. That's the right contract
# for a pure functional library — but at the worker boundary we need to
# tell apart "no qualifying appearances" (every candidate scene was
# correctly evaluated and rejected by thresholds) from "stage-wide
# failure" (every per-scene op raised and the lib skipped them all).
# Without this distinction, a broken SigLIP2 / S3 outage / SAM2 OOM
# would silently land at the user as "no appearances found".
#
# These wrappers count attempts vs. failures and re-raise — the lib's
# internal try/except still catches the raise, but the counters survive
# and let the worker call /fail with ``all_scenes_failed`` when every
# attempt failed.


class _CountingEmbedder:
    """Wraps a :class:`SiglipEmbedder`; counts attempts + failures.

    Used to detect a stage-wide SigLIP2 outage that the lib's
    per-scene try/except would otherwise mask as "no qualifying
    appearances". The first call (canonical crop) is expected to
    succeed — if it fails, we never reach the per-scene loop and the
    canonical-side exception propagates up. So at the F4 check site,
    ``attempted - 1`` == per-scene attempts and ``failed`` == per-scene
    failures (canonical successes contribute 0 to ``failed``).
    """

    def __init__(self, inner) -> None:
        self._inner = inner
        self.attempted = 0
        self.failed = 0

    def embed(self, image: "Image.Image") -> list[float]:
        self.attempted += 1
        try:
            return self._inner.embed(image)
        except Exception:
            self.failed += 1
            raise

    def per_scene_all_failed(self) -> bool:
        # Subtract 1 for the canonical embed (which must have
        # succeeded — otherwise we wouldn't reach the F4 check).
        per_scene_attempted = max(self.attempted - 1, 0)
        return per_scene_attempted > 0 and self.failed == per_scene_attempted

    @property
    def per_scene_attempted(self) -> int:
        return max(self.attempted - 1, 0)


class _CountingKeyframeFetcher:
    """Wraps a :class:`KeyframeFetcher`; counts attempts + failures."""

    def __init__(self, inner: KeyframeFetcherImpl) -> None:
        self._inner = inner
        self.attempted = 0
        self.failed = 0

    def fetch_scene_keyframe(self, scene_id: str) -> "Image.Image":
        self.attempted += 1
        try:
            return self._inner.fetch_scene_keyframe(scene_id)
        except Exception:
            self.failed += 1
            raise

    @property
    def all_attempts_failed(self) -> bool:
        return self.attempted > 0 and self.failed == self.attempted


class _CountingSam2Tracker:
    """Wraps a :class:`Sam2Tracker`; counts attempts + failures."""

    def __init__(self, inner: Sam2Tracker) -> None:
        self._inner = inner
        self.attempted = 0
        self.failed = 0

    def track(
        self,
        *,
        scene_id: str,
        anchor_bbox: BBoxXYWH,
        anchor_keyframe: "Image.Image",
        scene_video_url: str,
        sample_fps: int,
    ) -> list:
        self.attempted += 1
        try:
            return self._inner.track(
                scene_id=scene_id,
                anchor_bbox=anchor_bbox,
                anchor_keyframe=anchor_keyframe,
                scene_video_url=scene_video_url,
                sample_fps=sample_fps,
            )
        except Exception:
            self.failed += 1
            raise

    @property
    def all_attempts_failed(self) -> bool:
        return self.attempted > 0 and self.failed == self.attempted


@dataclass
class TrackJobMessage:
    """Decoded SQS body — matches
    ``heimdex_media_contracts.product.ProductTrackJob``."""

    job_id: UUID
    org_id: UUID
    video_id: UUID  # DriveFile UUID, NOT the OS string id
    catalog_entry_id: UUID
    requested_by_user_id: UUID
    duration_preset_sec: int
    tracker_version: str
    enumeration_prompt_version: str
    callback_base_url: str

    @classmethod
    def from_dict(cls, body: dict[str, Any]) -> "TrackJobMessage":
        return cls(
            job_id=UUID(body["job_id"]),
            org_id=UUID(body["org_id"]),
            video_id=UUID(body["video_id"]),
            catalog_entry_id=UUID(body["catalog_entry_id"]),
            requested_by_user_id=UUID(body["requested_by_user_id"]),
            duration_preset_sec=int(body["duration_preset_sec"]),
            tracker_version=str(body["tracker_version"]),
            enumeration_prompt_version=str(body["enumeration_prompt_version"]),
            # SECURITY (F3): tolerated-but-ignored. Future contract
            # bump should drop this field entirely.
            callback_base_url=str(body.get("callback_base_url", "")),
        )


def handle_track_job(
    *,
    message: dict[str, Any],
    settings: WorkerSettings,
    # Optional injection points for tests — production callers leave
    # these None and the function builds real clients from settings.
    api_client: ApiClient | None = None,
    embedder: SiglipEmbedder | None = None,
    tracker: Sam2Tracker | None = None,
    picker: SubsetPicker | None = None,
    s3_client: S3Client | None = None,
) -> None:
    """Single-message dispatch entrypoint. Raises on any failure;
    the dispatcher converts exceptions to the matching ``error_code``
    on the ``/fail`` callback."""
    decoded = TrackJobMessage.from_dict(message)

    # SECURITY (F3): the API base must come from worker settings only,
    # never from the queue body. ``decoded.callback_base_url`` is held
    # on the dataclass to mirror the contract but is deliberately
    # ignored here.
    api = api_client or ApiClient(
        base_url=settings.drive_api_base_url,
        internal_api_key=settings.drive_internal_api_key,
        service_id=settings.internal_service_id,
    )
    s3 = s3_client or _build_s3_client(settings)
    cost_accumulator = Decimal("0")

    try:
        # ─── 1. claim ──────────────────────────────────────────────
        # The api returns 409 for "already claimed / completed /
        # cancelled" — duplicate or stale SQS deliveries (visibility
        # expired, message redelivered, another worker already took
        # it). The api docs say: ack the message, do not retry.
        # Pre-fix the 409 propagated to the dispatcher's generic
        # exception path → /fail attempt (also 409s — we don't own
        # the lease) → re-raise → SQS redelivery → eventual DLQ for
        # what is fundamentally a no-op.
        try:
            api.claim(
                job_id=decoded.job_id,
                claimed_by=settings.worker_id,
                next_stage="tracking",
                lease_seconds=settings.worker_lease_seconds,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 409:
                logger.info(
                    "track_claim_conflict_acking_message",
                    extra={
                        "job_id": str(decoded.job_id),
                        "claimed_by": settings.worker_id,
                        "note": (
                            "job already claimed/completed/cancelled — "
                            "ack-delete the SQS message; do not retry"
                        ),
                    },
                )
                return
            raise

        # ─── 2. heartbeat: resolving ───────────────────────────────
        api.heartbeat(
            job_id=decoded.job_id,
            claimed_by=settings.worker_id,
            stage="tracking",
            progress_pct=10,
            progress_label="resolving catalog entry",
            cost_delta_usd=Decimal("0"),
            lease_seconds=settings.worker_lease_seconds,
        )

        # ─── 3. fetch canonical product crop ───────────────────────
        # TODO Phase 3c follow-up: add an internal endpoint to fetch
        # a single ProductCatalogEntry by id (org-scoped). The job
        # message currently carries only catalog_entry_id; the worker
        # needs canonical_crop_s3_key + bbox to seed retrieval +
        # SAM2. Until that endpoint lands, this raises and the
        # dispatcher reports /fail with internal_error.
        canonical_crop, canonical_bbox = _fetch_canonical_crop(
            api=api, s3=s3, decoded=decoded, settings=settings,
        )

        # ─── 4. heartbeat + 5. retrieve candidates ─────────────────
        api.heartbeat(
            job_id=decoded.job_id,
            claimed_by=settings.worker_id,
            stage="tracking",
            progress_pct=20,
            progress_label="retrieving candidate scenes",
            cost_delta_usd=Decimal("0"),
            lease_seconds=settings.worker_lease_seconds,
        )

        # Phase 2.5a scenes-with-keyframes: keyframe S3 keys per scene.
        # P2 fix: a 404 here means the DriveFile was deleted / failed
        # an org check between enqueue and processing — surface that
        # as ``video_not_found`` (matches enumerate-worker's behavior
        # in ``_fetch_keyframes``) instead of letting the dispatcher
        # report a generic ``internal_error``.
        try:
            scenes_resp = api.fetch_scenes_with_keyframes(
                file_id=decoded.video_id, org_id=decoded.org_id,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                api.fail(
                    job_id=decoded.job_id,
                    claimed_by=settings.worker_id,
                    cost_delta_usd=cost_accumulator,
                    error_code="video_not_found",
                    error_message=(
                        f"DriveFile {decoded.video_id} not found or "
                        f"not accessible to org {decoded.org_id}"
                    ),
                )
                return
            raise
        scene_id_to_kf = {
            s["scene_id"]: s["keyframe_s3_key"]
            for s in scenes_resp.get("scenes", [])
        }
        os_video_id = scenes_resp.get("video_id", "")

        embedder_impl = _CountingEmbedder(embedder or SiglipEmbedderImpl())
        coarse_client = CoarseRetrievalClientImpl(
            api=api, file_id=decoded.video_id, org_id=decoded.org_id,
        )
        keyframe_fetcher = _CountingKeyframeFetcher(
            KeyframeFetcherImpl(
                s3=s3,
                bucket=settings.drive_s3_bucket,
                scene_id_to_s3_key=scene_id_to_kf,
            )
        )
        cfg = _make_config(settings)

        candidate_scenes = retrieve_candidate_scenes(
            canonical_crop,
            video_id=os_video_id,
            embedder=embedder_impl,
            coarse_client=coarse_client,
            keyframe_fetcher=keyframe_fetcher,
            config=cfg,
        )

        # F4: distinguish "stage-wide outage" from "no qualifying
        # appearances". Every keyframe fetch raised → S3 outage / wrong
        # bucket / IAM revoke. Reporting that as "no appearances" hides
        # a real fault from the user.
        if keyframe_fetcher.all_attempts_failed:
            _fail_all_scenes(
                api, decoded, settings, cost_accumulator,
                stage="keyframe_fetch",
                attempted=keyframe_fetcher.attempted,
            )
            return

        # F4: same logic for per-scene SigLIP2 embedding. The lib's
        # ``retrieve_candidate_scenes`` swallows per-scene embed
        # exceptions, so a bad SigLIP2 deploy / corrupted HF cache
        # would silently land at the user as "no appearances" too.
        # The canonical embed must have succeeded (else the lib would
        # have raised before the loop), so all counted failures are
        # per-scene.
        if embedder_impl.per_scene_all_failed():
            _fail_all_scenes(
                api, decoded, settings, cost_accumulator,
                stage="siglip2_embed",
                attempted=embedder_impl.per_scene_attempted,
            )
            return

        if not candidate_scenes:
            _fail_no_qualifying(api, decoded, settings, cost_accumulator)
            return

        # ─── 6. heartbeat + 7. SAM2 propagation ────────────────────
        api.heartbeat(
            job_id=decoded.job_id,
            claimed_by=settings.worker_id,
            stage="tracking",
            progress_pct=40,
            progress_label=f"tracking {len(candidate_scenes)} scenes",
            cost_delta_usd=Decimal("0"),
            lease_seconds=settings.worker_lease_seconds,
        )

        # TODO Phase 3c-B: real scene_video_urls. Drive proxies live
        # at known S3 paths; needs a presigned URL helper or a
        # dedicated /internal endpoint. Stubbed here as
        # ``s3://{bucket}/proxies/{video_id}/{scene_id}.mp4`` which
        # the SAM2 stub raises on anyway.
        scene_video_urls = {
            cs.scene_id: f"s3://{settings.drive_s3_bucket}/proxies/{os_video_id}/{cs.scene_id}.mp4"
            for cs in candidate_scenes
        }

        tracker_impl = _CountingSam2Tracker(
            tracker or Sam2TrackerImpl(model_id=settings.sam2_model_id)
        )
        detections = propagate_within_candidate_scenes(
            candidates=candidate_scenes,
            canonical_bbox=canonical_bbox,
            tracker=tracker_impl,
            scene_video_urls=scene_video_urls,
            config=cfg,
        )

        # F4: every SAM2 track raised → systemic regression (model
        # OOM, every proxy URL 404, SAM2 weights wrong). Treat as a
        # job failure, not "no appearances".
        if tracker_impl.all_attempts_failed:
            _fail_all_scenes(
                api, decoded, settings, cost_accumulator,
                stage="sam2_track",
                attempted=tracker_impl.attempted,
            )
            return

        # ─── 8. assemble windows ───────────────────────────────────
        assembled = assemble_windows(detections, config=cfg)

        # ─── 9. fetch transcripts + OCR (for ALL assembled scenes) ─
        # P3 fix: rejected windows are persisted via /complete for
        # threshold tuning, so they MUST carry real OCR/narration
        # signals too. Limiting the fetch to accepted scenes would
        # serialize rejected rows with ``has_ocr_overlap=False``
        # regardless of actual scene text — skewing the very dataset
        # this worker is trying to preserve.
        all_assembled_scene_ids = sorted({w.scene_id for w in assembled})
        transcripts, ocr = _fetch_transcripts_ocr(
            api=api,
            file_id=decoded.video_id,
            org_id=decoded.org_id,
            scene_ids=all_assembled_scene_ids,
        )

        # ─── 10. annotate alignment ────────────────────────────────
        annotated = annotate_alignment(
            assembled,
            # TODO: the catalog entry's llm_label. Plumbed when
            # ``_fetch_canonical_crop`` returns the full entry rather
            # than just (image, bbox).
            label="",
            transcripts=transcripts,
            ocr=ocr,
        )

        # ─── 11. heartbeat + 12. score + pick ──────────────────────
        api.heartbeat(
            job_id=decoded.job_id,
            claimed_by=settings.worker_id,
            stage="tracking",
            progress_pct=80,
            progress_label="picking final clips",
            cost_delta_usd=Decimal("0"),
            lease_seconds=settings.worker_lease_seconds,
        )

        scored = score_windows(
            annotated,
            duration_preset_sec=decoded.duration_preset_sec,
            config=cfg,
        )
        if not scored:
            # Rejected windows still carry value (rejected_reason +
            # OCR + narration data) for threshold tuning. Persist them
            # via /complete with no render rather than dropping them
            # via /fail. Only when ``annotated`` is also empty (no
            # SAM2 detections at all) do we route to /fail.
            _terminate_no_render(
                api, decoded, settings, cost_accumulator, annotated=annotated,
            )
            return

        picker_impl = picker or _build_picker(settings)
        selected = select_subset(
            scored,
            picker=picker_impl,
            duration_preset_sec=decoded.duration_preset_sec,
            config=cfg,
        )
        if not selected:
            _terminate_no_render(
                api, decoded, settings, cost_accumulator, annotated=annotated,
            )
            return

        # ─── 13. build stitch plan ─────────────────────────────────
        # The plan is computed for completeness (and so the lib's
        # build_stitch_plan invariants are exercised) but NOT shipped
        # to the api — ``_CompleteRequest`` (extra='forbid') has no
        # ``stitching_plan`` field. Phase 3c-B turns this plan into a
        # ``CompositionSpec`` and POSTs to ``/api/shorts/render``;
        # the resulting ``render_job_id`` is the only thing the api
        # needs to persist on the tracking row.
        _ = build_stitch_plan(
            selected,
            duration_target_sec=decoded.duration_preset_sec,
            config=cfg,
        )

        # ─── 14. enqueue render + complete ─────────────────────────
        # TODO Phase 3c-B: enqueue the render via the api's
        # /api/shorts/render endpoint and pass the resulting job id.
        # For scaffold the render enqueue is a placeholder; the api
        # callback (/complete) accepts ``render_job_id=None`` so the
        # worker can mark the job complete with appearances populated
        # — UI surfaces "tracked, render pending".
        render_job_id: UUID | None = None

        api.complete_track(
            job_id=decoded.job_id,
            claimed_by=settings.worker_id,
            cost_delta_usd=cost_accumulator,
            appearances=_serialize_appearances(annotated, decoded),
            render_job_id=render_job_id,
        )
    finally:
        api.close()


# ─── helpers ─────────────────────────────────────────────────────────


def _make_config(settings: WorkerSettings) -> TrackingConfig:
    return TrackingConfig(
        coarse_prefilter_threshold=settings.coarse_prefilter_threshold,
        precise_pass_threshold=settings.precise_pass_threshold,
        coarse_top_k=settings.coarse_top_k,
        sam2_sample_fps=settings.sam2_sample_fps,
        min_window_duration_ms=settings.min_window_duration_ms,
        min_avg_bbox_area_pct=settings.min_avg_bbox_area_pct,
        min_avg_confidence=settings.min_avg_confidence,
        merge_gap_threshold_ms=settings.merge_gap_threshold_ms,
        max_windows_per_product=settings.max_windows_per_product,
        score_weight_prominence=settings.score_weight_prominence,
        score_weight_narration=settings.score_weight_narration,
        score_weight_ocr=settings.score_weight_ocr,
        score_weight_duration_fitness=settings.score_weight_duration_fitness,
        score_weight_spread_bonus=settings.score_weight_spread_bonus,
        subset_duration_overshoot_factor=settings.subset_duration_overshoot_factor,
        tracker_version=settings.tracker_version,
        subset_picker_version=settings.subset_picker_version,
    )


def _build_s3_client(settings: WorkerSettings) -> S3Client:
    # SDK contract: ``S3Client(bucket: str, client=None)`` — credentials
    # come from boto3's standard chain (env / IAM role / metadata
    # service). Passing region/endpoint/credential kwargs would
    # TypeError; the prior scaffold guessed at a non-existent
    # signature.
    return S3Client(bucket=settings.drive_s3_bucket)


def _build_picker(settings: WorkerSettings) -> SubsetPicker:
    if not settings.openai_api_key:
        # Fallback to GreedyPicker when OpenAI isn't configured —
        # safer than crashing in environments where the LLM picker
        # isn't intended to run (local dev, on-prem without an
        # OpenAI account).
        from heimdex_media_pipelines.product_track.subset_selector import GreedyPicker
        return GreedyPicker()

    from openai import OpenAI
    client = OpenAI(api_key=settings.openai_api_key)
    return OpenAIPicker(
        client=client,
        model=settings.openai_model,
        timeout_sec=settings.openai_timeout_sec,
    )


def _fetch_canonical_crop(
    *,
    api: ApiClient,
    s3: S3Client,
    decoded: TrackJobMessage,
    settings: WorkerSettings,
) -> tuple["Image.Image", BBoxXYWH]:
    """TODO Phase 3c follow-up: add ``GET /internal/products/catalog/{catalog_entry_id}``
    on the api side, returning ``{canonical_crop_s3_key, bbox_xywh,
    llm_label, ...}``. The worker would download the crop from S3
    and return it + the bbox here.

    Until that endpoint lands, this stub raises so the dispatcher
    fails the job with a clear error rather than silently producing
    no appearances."""
    raise NotImplementedError(
        f"Phase 3c-A scaffold: GET /internal/products/catalog/{decoded.catalog_entry_id} "
        f"endpoint pending. Worker can't fetch canonical crop without it. "
        f"Phase 3c-B follow-up adds the endpoint."
    )


def _fetch_transcripts_ocr(
    *,
    api: ApiClient,
    file_id: UUID,
    org_id: UUID,
    scene_ids: list[str],
) -> tuple[
    dict[str, list[TranscriptSegment]],
    dict[str, list[OcrSegment]],
]:
    """Fetch per-scene transcripts + OCR via the Phase 3b
    ``/scenes-content`` endpoint. The contract is that scene-level
    ``start_ms`` / ``end_ms`` bound the transcript and OCR text;
    the alignment lib treats segments without explicit bounds as
    spanning the whole scene."""
    if not scene_ids:
        return {}, {}

    rows = api.fetch_scenes_content(
        file_id=file_id, org_id=org_id, scene_ids=scene_ids,
    )
    transcripts: dict[str, list[TranscriptSegment]] = {}
    ocr: dict[str, list[OcrSegment]] = {}
    for r in rows:
        sid = str(r["scene_id"])
        start_ms = int(r.get("start_ms", 0) or 0)
        end_ms = int(r.get("end_ms", 0) or 0)
        transcript_text = r.get("transcript_raw") or ""
        ocr_text = r.get("ocr_text_raw") or ""
        if transcript_text:
            transcripts[sid] = [
                TranscriptSegment(
                    scene_id=sid,
                    text=transcript_text,
                    start_ms=start_ms,
                    end_ms=max(end_ms, start_ms + 1),
                )
            ]
        if ocr_text:
            ocr[sid] = [OcrSegment(scene_id=sid, text=ocr_text)]
    return transcripts, ocr


def _fail_all_scenes(
    api: ApiClient,
    decoded: TrackJobMessage,
    settings: WorkerSettings,
    cost: Decimal,
    *,
    stage: str,
    attempted: int,
) -> None:
    """F4: terminal failure for stage-wide outages — distinguished
    from ``_fail_no_qualifying`` (every candidate was evaluated and
    no window cleared the precision threshold).

    The API's ``_FailRequest.error_code`` enum doesn't carry an
    ``all_scenes_failed`` literal, so we use ``internal_error`` and
    embed the stage + attempt count in ``error_message``. Worker logs
    capture the structured detail.
    """
    api.fail(
        job_id=decoded.job_id,
        claimed_by=settings.worker_id,
        cost_delta_usd=cost,
        error_code="internal_error",
        error_message=(
            f"all {attempted} candidate scene operations failed at stage "
            f"{stage!r} — likely a stage-wide regression, not absent product"
        ),
    )


def _fail_no_qualifying(
    api: ApiClient,
    decoded: TrackJobMessage,
    settings: WorkerSettings,
    cost: Decimal,
) -> None:
    """Terminal failure for "tracker found nothing matching the
    precision threshold". Distinct from ``_fail_all_scenes`` (where
    every per-scene op raised) and from ``/complete`` (which the api
    400s when ``appearances=[]``).

    Maps to ``error_code="tracker_low_confidence_global"`` — the api
    enum literal that fits "we ran the pipeline but produced no
    qualifying windows".
    """
    api.fail(
        job_id=decoded.job_id,
        claimed_by=settings.worker_id,
        cost_delta_usd=cost,
        error_code="tracker_low_confidence_global",
        error_message=(
            "no candidate scenes cleared the precision/IoU/duration "
            "thresholds for this product"
        ),
    )


def _terminate_no_render(
    api: ApiClient,
    decoded: TrackJobMessage,
    settings: WorkerSettings,
    cost: Decimal,
    *,
    annotated: list,
) -> None:
    """Terminal handler for "tracker produced something, but no
    window qualifies for rendering". Two sub-cases:

    * ``annotated`` is non-empty (SAM2 detected scenes; thresholds /
      subset selection rejected them): /complete with the rejected
      appearances + ``render_job_id=None``. The api persists them
      (with ``rejected_reason`` set) for threshold tuning + UI
      surfacing of "tracked, no qualifying windows".
    * ``annotated`` is empty (SAM2 produced no detections): /fail
      with ``tracker_low_confidence_global``. The api ``/complete``
      400s on empty appearances, so we can't /complete here.
    """
    if annotated:
        api.complete_track(
            job_id=decoded.job_id,
            claimed_by=settings.worker_id,
            cost_delta_usd=cost,
            appearances=_serialize_appearances(annotated, decoded),
            render_job_id=None,
        )
        return
    _fail_no_qualifying(api, decoded, settings, cost)


def _serialize_appearances(
    annotated: list,
    decoded: TrackJobMessage,
) -> list[dict[str, Any]]:
    """Convert lib-level ``AnnotatedWindow`` to the api's
    ``_AppearancePayload`` shape (extra='forbid' — must match exactly).

    The api derives ``catalog_entry_id`` from the claimed job row, so
    we MUST NOT send it on each appearance. Scaffold's earlier
    ``_AppearancePayload``-incompatible shape would 422 on every
    successful tracking completion.
    """
    out = []
    for w in annotated:
        out.append({
            "scene_id": w.scene_id,
            "window_start_ms": w.window_start_ms,
            "window_end_ms": w.window_end_ms,
            "avg_bbox_area_pct": w.avg_bbox_area_pct,
            "avg_confidence": w.avg_confidence,
            "has_narration_mention": w.has_narration_mention,
            "has_ocr_overlap": w.has_ocr_overlap,
            "co_appearing_catalog_entry_ids": [],
            "raw_bbox_track_s3_key": None,  # frame-level track upload TODO
            "tracker_version": decoded.tracker_version,
            "rejected_reason": w.rejected_reason,
        })
    return out
