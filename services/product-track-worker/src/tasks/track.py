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
    StitchPlan,
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
            callback_base_url=str(body["callback_base_url"]),
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

    api = api_client or ApiClient(
        base_url=decoded.callback_base_url or settings.drive_api_base_url,
        internal_api_key=settings.drive_internal_api_key,
        service_id=settings.internal_service_id,
    )
    s3 = s3_client or _build_s3_client(settings)
    cost_accumulator = Decimal("0")

    try:
        # ─── 1. claim ──────────────────────────────────────────────
        api.claim(
            job_id=decoded.job_id,
            claimed_by=settings.worker_id,
            next_stage="tracking",
            lease_seconds=settings.worker_lease_seconds,
        )

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
        scenes_resp = api.fetch_scenes_with_keyframes(
            file_id=decoded.video_id, org_id=decoded.org_id,
        )
        scene_id_to_kf = {
            s["scene_id"]: s["keyframe_s3_key"]
            for s in scenes_resp.get("scenes", [])
        }
        os_video_id = scenes_resp.get("video_id", "")

        embedder_impl = embedder or SiglipEmbedderImpl()
        coarse_client = CoarseRetrievalClientImpl(
            api=api, file_id=decoded.video_id, org_id=decoded.org_id,
        )
        keyframe_fetcher = KeyframeFetcherImpl(
            s3=s3,
            bucket=settings.drive_s3_bucket,
            scene_id_to_s3_key=scene_id_to_kf,
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

        if not candidate_scenes:
            _complete_no_qualifying(api, decoded, settings, cost_accumulator)
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

        tracker_impl = tracker or Sam2TrackerImpl(model_id=settings.sam2_model_id)
        detections = propagate_within_candidate_scenes(
            candidates=candidate_scenes,
            canonical_bbox=canonical_bbox,
            tracker=tracker_impl,
            scene_video_urls=scene_video_urls,
            config=cfg,
        )

        # ─── 8. assemble windows ───────────────────────────────────
        assembled = assemble_windows(detections, config=cfg)

        # ─── 9. fetch transcripts + OCR (only for accepted scenes) ─
        accepted_scene_ids = sorted(
            {w.scene_id for w in assembled if w.is_accepted}
        )
        transcripts, ocr = _fetch_transcripts_ocr(
            api=api,
            file_id=decoded.video_id,
            org_id=decoded.org_id,
            scene_ids=accepted_scene_ids,
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
            _complete_no_qualifying(api, decoded, settings, cost_accumulator,
                                    annotated=annotated)
            return

        picker_impl = picker or _build_picker(settings)
        selected = select_subset(
            scored,
            picker=picker_impl,
            duration_preset_sec=decoded.duration_preset_sec,
            config=cfg,
        )
        if not selected:
            _complete_no_qualifying(api, decoded, settings, cost_accumulator,
                                    annotated=annotated)
            return

        # ─── 13. build stitch plan ─────────────────────────────────
        plan = build_stitch_plan(
            selected,
            duration_target_sec=decoded.duration_preset_sec,
            config=cfg,
        )

        # ─── 14. enqueue render + complete ─────────────────────────
        # TODO Phase 3c follow-up: enqueue the render via the api's
        # /api/shorts/render endpoint with the stitch plan converted
        # to a CompositionSpec. For Phase 3c-A scaffold the render
        # enqueue is a placeholder; the api callback (/complete)
        # accepts ``render_job_id=None`` so the worker can mark the
        # job complete with a populated stitch_plan but no render
        # yet — UI surfaces "tracked, render pending".
        render_job_id: UUID | None = None

        api.complete_track(
            job_id=decoded.job_id,
            claimed_by=settings.worker_id,
            cost_delta_usd=cost_accumulator,
            appearances=_serialize_appearances(annotated, decoded, plan),
            stitching_plan=_serialize_stitching_plan(plan, decoded),
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
    return S3Client(
        region=settings.s3_region,
        endpoint_url=settings.s3_endpoint_url or None,
        access_key_id=settings.aws_access_key_id or None,
        secret_access_key=settings.aws_secret_access_key or None,
    )


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


def _complete_no_qualifying(
    api: ApiClient,
    decoded: TrackJobMessage,
    settings: WorkerSettings,
    cost: Decimal,
    *,
    annotated: list | None = None,
) -> None:
    """Terminal complete with no stitch plan / no render. The api
    contract: empty ``stitching_plan`` + ``render_job_id=None`` ⇒
    UI shows "no qualifying appearances found" and the job lifecycle
    closes cleanly. We still persist the assembled appearances (if
    any) so threshold tuning has visibility."""
    appearances = (
        _serialize_appearances(annotated, decoded, None) if annotated else []
    )
    api.complete_track(
        job_id=decoded.job_id,
        claimed_by=settings.worker_id,
        cost_delta_usd=cost,
        appearances=appearances,
        stitching_plan=None,
        render_job_id=None,
    )


def _serialize_appearances(
    annotated: list,
    decoded: TrackJobMessage,
    plan: StitchPlan | None,
) -> list[dict[str, Any]]:
    """Convert lib-level ``AnnotatedWindow`` to the api callback's
    ``AppearanceWindow`` shape (matches the contracts schema)."""
    out = []
    for w in annotated:
        out.append({
            "catalog_entry_id": str(decoded.catalog_entry_id),
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


def _serialize_stitching_plan(
    plan: StitchPlan, decoded: TrackJobMessage,
) -> dict[str, Any]:
    return {
        "catalog_entry_id": str(decoded.catalog_entry_id),
        "video_id": str(decoded.video_id),
        "duration_target_sec": plan.duration_target_sec,
        "duration_actual_ms": plan.duration_actual_ms,
        "windows": [
            {
                "scene_id": s.window.scene_id,
                "source_start_ms": s.window.window_start_ms,
                "source_end_ms": s.window.window_end_ms,
                "composite_score": s.composite_score,
                "score_components": s.score_components,
            }
            for s in plan.windows
        ],
        "scorer_version": plan.scorer_version,
        "subset_picker_version": plan.subset_picker_version,
    }
