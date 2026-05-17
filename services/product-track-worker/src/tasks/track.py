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
from dataclasses import dataclass, replace
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
from heimdex_worker_sdk import emit_event
from heimdex_worker_sdk.s3 import S3Client

from src.api_client import ApiClient
from src.openai_picker import OpenAIPicker
from src.proxy_download import downloaded_proxy
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
    """Wraps a :class:`Sam2Tracker`; counts attempts + failures.

    PR F: when ``job_id`` / ``org_id`` / ``video_id`` are provided
    at construction, also emits a structured ``worker_event`` per
    scene-level exception with the exception type + message. The
    lib's ``propagate_within_candidate_scenes`` catches per-scene
    exceptions and only stdout-logs them — without this wrapper,
    every SAM2 failure mode collapses into the generic
    ``scan_order_product_sam2_f4`` aggregate and operators have to
    chase Aircloud logs for the actual exception text. With this
    wrapper, the next failure's per-scene exception is one SQL
    query away.
    """

    def __init__(
        self,
        inner: Sam2Tracker,
        *,
        job_id: str | None = None,
        org_id: str | None = None,
        video_id: str | None = None,
    ) -> None:
        self._inner = inner
        self.attempted = 0
        self.failed = 0
        self._job_id = job_id
        self._org_id = org_id
        self._video_id = video_id

    def track(
        self,
        *,
        scene_id: str,
        anchor_bbox: BBoxXYWH,
        anchor_keyframe: "Image.Image",
        full_video_path: str,
        scene_start_ms: int,
        scene_end_ms: int,
        sample_fps: int,
    ) -> list:
        self.attempted += 1
        try:
            return self._inner.track(
                scene_id=scene_id,
                anchor_bbox=anchor_bbox,
                anchor_keyframe=anchor_keyframe,
                full_video_path=full_video_path,
                scene_start_ms=scene_start_ms,
                scene_end_ms=scene_end_ms,
                sample_fps=sample_fps,
            )
        except Exception as exc:
            self.failed += 1
            # Best-effort per-scene diagnostic — the worker has full
            # context the lib lacks, so emit before re-raise. Skip
            # cleanly if construction context wasn't supplied (unit
            # tests that don't care about the diagnostic path).
            if self._job_id is not None:
                try:
                    emit_event(
                        service="product-track-worker",
                        event_name="sam2_track_scene_failed",
                        category="job_failure",
                        level="WARNING",
                        org_id=self._org_id,
                        job_id=self._job_id,
                        video_id=self._video_id,
                        message=f"{type(exc).__name__}: {exc}"[:1000],
                        metadata={
                            "scene_id": scene_id,
                            "scene_start_ms": scene_start_ms,
                            "scene_end_ms": scene_end_ms,
                            "exception_type": type(exc).__name__,
                            "exception_message": str(exc)[:1000],
                        },
                    )
                except Exception:  # noqa: BLE001
                    # emit_event is fire-and-forget; never let a
                    # diagnostic-emission failure poison the actual
                    # error path.
                    logger.exception("sam2_track_scene_failed_emit_failed")
            raise

    @property
    def all_attempts_failed(self) -> bool:
        return self.attempted > 0 and self.failed == self.attempted


@dataclass
class TrackJobMessage:
    """Decoded SQS body — matches
    ``heimdex_media_contracts.product.ProductTrackJob`` (v0.14.0+).

    Fields ``catalog_entry_id`` and ``duration_preset_sec`` are
    Optional in v0.14.0 to support the wizard scan_order parent flow,
    which has no single catalog entry to anchor on.

    Mode dispatch (in ``handle_track_job`` below):
      * ``mode='enumerate'`` (default) AND ``catalog_entry_id`` set
        → legacy single-product flow (existing track pipeline).
      * ``mode='scan_order'`` AND ``catalog_entry_id`` is None
        → wizard parent — process the whole video catalog. Real
        per-catalog loop lands in PR #5b; PR #5a stubs this with a
        clear ``not_yet_implemented`` failure so the dispatcher
        doesn't crash on unknown shapes.
      * ``mode='render_child'`` → reserved; render_child rows are
        processed in-API by the child runner, NOT via SQS. If we
        ever see one here, it's a bug — fail loudly.
    """

    job_id: UUID
    org_id: UUID
    video_id: UUID  # DriveFile UUID, NOT the OS string id
    catalog_entry_id: UUID | None
    requested_by_user_id: UUID
    duration_preset_sec: int | None
    tracker_version: str
    enumeration_prompt_version: str
    callback_base_url: str

    # v0.14.0 wizard fields — None for legacy senders.
    mode: str = "enumerate"
    length_seconds: int | None = None
    requested_count: int | None = None
    time_range_start_ms: int | None = None
    time_range_end_ms: int | None = None
    product_distribution: str | None = None
    language: str | None = None
    intent: str | None = None

    @classmethod
    def from_dict(cls, body: dict[str, Any]) -> "TrackJobMessage":
        catalog_entry_id_raw = body.get("catalog_entry_id")
        duration_preset_raw = body.get("duration_preset_sec")
        return cls(
            job_id=UUID(body["job_id"]),
            org_id=UUID(body["org_id"]),
            video_id=UUID(body["video_id"]),
            catalog_entry_id=(
                UUID(catalog_entry_id_raw) if catalog_entry_id_raw else None
            ),
            requested_by_user_id=UUID(body["requested_by_user_id"]),
            duration_preset_sec=(
                int(duration_preset_raw) if duration_preset_raw is not None else None
            ),
            tracker_version=str(body["tracker_version"]),
            enumeration_prompt_version=str(body["enumeration_prompt_version"]),
            # SECURITY (F3): tolerated-but-ignored. Future contract
            # bump should drop this field entirely.
            callback_base_url=str(body.get("callback_base_url", "")),
            mode=str(body.get("mode", "enumerate")),
            length_seconds=(
                int(body["length_seconds"]) if "length_seconds" in body else None
            ),
            requested_count=(
                int(body["requested_count"]) if "requested_count" in body else None
            ),
            time_range_start_ms=(
                int(body["time_range_start_ms"])
                if "time_range_start_ms" in body
                else None
            ),
            time_range_end_ms=(
                int(body["time_range_end_ms"])
                if "time_range_end_ms" in body
                else None
            ),
            product_distribution=body.get("product_distribution"),
            language=body.get("language"),
            intent=body.get("intent"),
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

        # ─── 1.5 mode dispatch ─────────────────────────────────────
        # Phase 4 PR #5b — wizard scan_order parent flow runs the
        # per-catalog loop in ``_handle_scan_order_parent``. The
        # legacy single-product flow (mode='enumerate' with
        # catalog_entry_id set) continues below this branch.
        if decoded.mode == "scan_order":
            _handle_scan_order_parent(
                decoded=decoded,
                settings=settings,
                api=api,
                s3=s3,
                embedder=embedder,
                tracker=tracker,
                picker=picker,  # NOT used by parent — children own picking
            )
            return
        if decoded.mode == "render_child":
            # render_child rows are processed in-API by the child
            # runner, never via SQS. Reaching here = bug. Fail loudly.
            api.fail(
                job_id=decoded.job_id,
                claimed_by=settings.worker_id,
                cost_delta_usd=Decimal("0"),
                error_code="internal_error",
                error_message=(
                    "render_child rows must be processed in-API by the "
                    "child runner, not via the worker SQS path"
                ),
            )
            return
        if decoded.mode != "enumerate":
            api.fail(
                job_id=decoded.job_id,
                claimed_by=settings.worker_id,
                cost_delta_usd=Decimal("0"),
                error_code="internal_error",
                error_message=f"unknown track-worker mode={decoded.mode!r}",
            )
            return

        # Legacy single-product flow requires both fields. Defensive
        # check: if the API somehow published a mode='enumerate'
        # message without ``catalog_entry_id`` (shouldn't happen post
        # #5a since publish_product_track_job branches on mode), fail
        # clearly rather than crashing on the None-deref later.
        if decoded.catalog_entry_id is None:
            api.fail(
                job_id=decoded.job_id,
                claimed_by=settings.worker_id,
                cost_delta_usd=Decimal("0"),
                error_code="internal_error",
                error_message=(
                    "legacy track flow requires catalog_entry_id but the "
                    "message body had it unset"
                ),
            )
            return

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
        # Resolves the catalog entry's seed (canonical crop image,
        # anchor bbox, llm label) via the Phase 3c-B endpoint
        # ``GET /internal/products/catalog/{catalog_entry_id}`` plus
        # an S3 download for the crop bytes.
        canonical_crop, canonical_bbox, llm_label = _fetch_canonical_crop(
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
        raw_scenes = scenes_resp.get("scenes", [])
        scene_id_to_kf = {
            s["scene_id"]: s["keyframe_s3_key"] for s in raw_scenes
        }
        scene_id_to_timing: dict[str, tuple[int, int]] = {
            s["scene_id"]: (int(s["start_ms"]), int(s["end_ms"]))
            for s in raw_scenes
        }
        os_video_id = scenes_resp.get("video_id", "")

        # Single-proxy fast-fail: ``proxy_s3_key`` is None when
        # transcode hasn't completed for this video. Surface as a
        # distinct ``proxy_missing`` error code so the wizard can
        # show "video isn't ready yet" rather than the generic
        # ``internal_error``.
        proxy_s3_key = scenes_resp.get("proxy_s3_key")
        if not proxy_s3_key:
            api.fail(
                job_id=decoded.job_id,
                claimed_by=settings.worker_id,
                cost_delta_usd=cost_accumulator,
                error_code="proxy_missing",
                error_message=(
                    f"DriveFile {decoded.video_id} has no proxy_s3_key — "
                    f"transcode incomplete; retry once the video shows "
                    f"as indexed."
                ),
            )
            return

        embedder_impl = _CountingEmbedder(embedder or SiglipEmbedderImpl())
        coarse_client = CoarseRetrievalClientImpl(
            api=api,
            file_id=decoded.video_id,
            org_id=decoded.org_id,
            scene_id_to_timing=scene_id_to_timing,
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

        # Download the full-video proxy ONCE per job message; the
        # SAM2 wrapper seeks each scene's window in-memory. Tempdir
        # is cleaned up on context exit (success OR exception via
        # F4) so we never leak across retries on Aircloud's tight
        # /tmp.
        tracker_impl = _CountingSam2Tracker(
            tracker or Sam2TrackerImpl(model_id=settings.sam2_model_id),
            job_id=str(decoded.job_id),
            org_id=str(decoded.org_id),
            video_id=str(decoded.video_id),
        )
        with downloaded_proxy(
            s3=s3,
            proxy_s3_key=proxy_s3_key,
            job_id_for_naming=str(decoded.job_id),
            expected_size_bytes=_resolve_proxy_size(s3, proxy_s3_key),
        ) as full_video_path:
            detections = propagate_within_candidate_scenes(
                candidates=candidate_scenes,
                canonical_bbox=canonical_bbox,
                tracker=tracker_impl,
                full_video_path=str(full_video_path),
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
        # ``llm_label`` is the product's name (e.g. "핑크 세럼 병"),
        # used by the alignment lib to mark
        # ``has_narration_mention`` / ``has_ocr_overlap`` per window
        # via tokenised substring matching.
        annotated = annotate_alignment(
            assembled,
            label=llm_label,
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

        # Roll the LLM picker's accumulated USD spend into the job's
        # cost ledger. Pre-fix the api's per-org daily-budget gate
        # undercounted every track job that used the OpenAIPicker
        # because ``cost_delta_usd`` was always 0 — the picker
        # reports cost via a public ``total_cost_usd`` attribute that
        # we read here. ``getattr`` with default keeps GreedyPicker
        # / test-injected mocks compatible.
        cost_accumulator += getattr(picker_impl, "total_cost_usd", Decimal("0"))

        if not selected:
            _terminate_no_render(
                api, decoded, settings, cost_accumulator, annotated=annotated,
            )
            return

        # ─── 13. build stitch plan ─────────────────────────────────
        plan = build_stitch_plan(
            selected,
            duration_target_sec=decoded.duration_preset_sec,
            config=cfg,
        )

        # ─── 14. enqueue render + complete ─────────────────────────
        # Build a ``CompositionSpec`` from the stitch plan windows
        # (chronological hard cuts; per-clip ``source_start_ms`` /
        # ``source_end_ms`` ranges) and POST to the api's internal
        # render endpoint. The api forwards to
        # ``ShortsRenderService.create_render_job`` with
        # ``user_id=job.requested_by_user_id`` derived server-side
        # (workers don't carry user JWTs). Returns the new
        # ``RenderJob.id`` which we ship on /complete.
        composition_spec = _build_composition_spec(
            plan=plan, os_video_id=os_video_id,
        )
        try:
            render_job_id: UUID | None = api.enqueue_render(
                scan_job_id=decoded.job_id,
                claimed_by=settings.worker_id,
                video_id=os_video_id,
                title=llm_label or None,
                composition=composition_spec,
            )
        except httpx.HTTPStatusError as exc:
            # Render enqueue failure is recoverable from the user's
            # POV: the tracker successfully produced appearances,
            # the api just couldn't kick off ffmpeg. /fail with the
            # api enum literal for this exact case (rather than
            # internal_error) so the user-facing UI can render the
            # right message + retry affordance.
            logger.exception(
                "track_render_enqueue_failed",
                extra={
                    "job_id": str(decoded.job_id),
                    "status_code": exc.response.status_code,
                },
            )
            api.fail(
                job_id=decoded.job_id,
                claimed_by=settings.worker_id,
                cost_delta_usd=cost_accumulator,
                error_code="render_enqueue_failed",
                error_message=(
                    f"render enqueue failed status={exc.response.status_code}: "
                    f"{str(exc)[:1500]}"
                ),
            )
            return

        api.complete_track(
            job_id=decoded.job_id,
            claimed_by=settings.worker_id,
            cost_delta_usd=cost_accumulator,
            appearances=_serialize_appearances(annotated, decoded, settings),
            render_job_id=render_job_id,
        )
    finally:
        api.close()


# ─── helpers ─────────────────────────────────────────────────────────


def _resolve_proxy_size(s3: S3Client, proxy_s3_key: str) -> int | None:
    """Best-effort ``head_object`` to learn the proxy's expected size.

    Returns ``None`` on any failure so the integrity check in
    ``downloaded_proxy`` falls back to the ``size > 0`` gate. We
    explicitly do NOT propagate the head_object exception here:
    the actual download attempt below will surface the real S3
    error if there is one, and it would be silly to fail the job
    on a HEAD that we only use as a sanity check.

    Reaches into the SDK's underlying boto3 client because
    ``heimdex_worker_sdk.s3.S3Client`` doesn't expose a public
    size accessor (only ``exists``). Treat this as a worker-local
    convenience; if the SDK ever grows ``head_object_size``,
    switch to that.
    """
    try:
        # ``S3Client._client`` is the boto3 client. ``S3Client._bucket``
        # is the bucket bound at construction. Both private but stable
        # within our SDK.
        resp = s3._client.head_object(Bucket=s3._bucket, Key=proxy_s3_key)  # noqa: SLF001
    except Exception:
        logger.warning(
            "proxy_head_object_failed",
            extra={"proxy_s3_key": proxy_s3_key},
            exc_info=True,
        )
        return None

    # Defensive shape check. boto3 returns a dict with int
    # ``ContentLength``; anything else (notably MagicMock objects in
    # tests, where ``__int__`` returns 1 by default) is unsafe to
    # feed into the integrity gate. Skip the size match in that case
    # — the helper's ``size > 0`` floor still applies.
    if not isinstance(resp, dict):
        return None
    size = resp.get("ContentLength")
    return size if isinstance(size, int) else None


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


def _build_composition_spec(
    *,
    plan: "StitchPlan",
    os_video_id: str,
) -> dict[str, Any]:
    """Convert a Phase 3a ``StitchPlan`` to the
    ``CompositionSpec.model_dump(mode='json')`` shape that
    ``/api/shorts/render`` accepts.

    Each ``StitchPlan.windows[i]`` (a ``StitchedClip`` with an
    inner ``window`` carrying ``scene_id`` + ``window_start_ms`` +
    ``window_end_ms``) becomes one ``SceneClipSpec``. Clips are
    placed back-to-back chronologically on the composition timeline
    (hard cuts; no transitions in v1 per plan §6.2 step 8).

    ``video_id`` is the OpenSearch string id (``gd_abc``) — same
    shape ``RenderJobCreate.video_id`` already accepts. Source type
    is hard-coded ``gdrive``; future Drive variants (removable
    disk, local) will need a worker-side switch but that's
    deferred until Drive picks up multi-source ingestion.
    """
    timeline_cursor_ms = 0
    scene_clips: list[dict[str, Any]] = []
    for scored in plan.windows:
        # ``StitchPlan.windows`` is ``list[ScoredWindow]``;
        # ``ScoredWindow.window`` is the underlying
        # ``AnnotatedWindow`` with the actual time range.
        window = scored.window
        clip_duration_ms = window.window_end_ms - window.window_start_ms
        scene_clips.append({
            "scene_id": window.scene_id,
            "video_id": os_video_id,
            "source_type": "gdrive",
            "start_ms": window.window_start_ms,
            "end_ms": window.window_end_ms,
            "timeline_start_ms": timeline_cursor_ms,
            "volume": 1.0,
        })
        timeline_cursor_ms += clip_duration_ms

    return {
        "scene_clips": scene_clips,
        # Output / subtitles / overlays / transitions intentionally
        # omitted — server-side ``CompositionSpec`` defaults give
        # 9:16 vertical 720p mp4 hard-cut, which matches the v1
        # product mode shorts UX.
    }


def _fetch_canonical_crop(
    *,
    api: ApiClient,
    s3: S3Client,
    decoded: TrackJobMessage,
    settings: WorkerSettings,
) -> tuple["Image.Image", BBoxXYWH, str]:
    """Phase 3c-B: resolve the catalog entry's seed metadata
    (canonical crop image, anchor bbox, llm label) for the track
    pipeline.

    Steps:
      1. GET ``/internal/products/catalog/{catalog_entry_id}`` —
         returns ``canonical_crop_s3_key + bbox + llm_label``.
      2. Verify the entry's ``org_id`` matches the job's. The api
         already enforces Pattern B tenant scoping, but a
         defence-in-depth check is cheap and catches misconfigured
         multi-tenant setups loudly.
      3. Download the crop bytes from S3 via the existing client.
         The crop S3 key was written by product-enumerate-worker at
         ``products/{org_id}/{video_id}/{uuid}.jpg`` (see
         ``_upload_crops_and_build_payload``); same bucket as
         everything else, so the SDK's S3Client just works.
      4. Decode to a PIL Image. The lib expects RGB so we convert
         eagerly (SigLIP2 requires 3-channel input — JPEGs are
         already RGB but normalising here keeps the contract
         explicit).

    Returns ``(canonical_crop, canonical_bbox, llm_label)``. The
    caller passes ``llm_label`` to ``annotate_alignment`` so
    ``has_narration_mention`` / ``has_ocr_overlap`` can match
    against the product's name in transcripts + OCR.

    Failure modes:
      * api 404 → ``RuntimeError`` (catalog entry not found / cross
        tenant). Bubbles to dispatcher → /fail with internal_error.
        We do NOT special-case to ``video_not_found``: the catalog
        row predates the track job (enumerated earlier) and missing
        it indicates row deletion / corruption, not a missing video.
      * S3 missing the crop bytes → ``FileNotFoundError`` (same
        bubbling path). Operators see the s3_key in the error
        message so they can locate the gap in the enum-side upload.
      * org mismatch → ``RuntimeError`` (would only happen if the
        api side is misconfigured to omit Pattern B; defence in
        depth).
    """
    payload = api.fetch_catalog_entry(
        catalog_entry_id=decoded.catalog_entry_id,
        org_id=decoded.org_id,
    )

    payload_org_id = UUID(str(payload["org_id"]))
    if payload_org_id != decoded.org_id:
        raise RuntimeError(
            f"catalog entry {decoded.catalog_entry_id} org "
            f"{payload_org_id} != job org {decoded.org_id}"
        )

    s3_key = str(payload["canonical_crop_s3_key"])
    body = s3.get_object_bytes(s3_key)
    if body is None:
        raise FileNotFoundError(
            f"canonical crop S3 object missing for catalog_entry_id="
            f"{decoded.catalog_entry_id} s3_key={s3_key}"
        )

    from PIL import Image as _PILImage
    canonical_crop = _PILImage.open(io.BytesIO(body)).convert("RGB")

    bbox_payload = payload["canonical_bbox"]
    canonical_bbox = BBoxXYWH(
        x=int(bbox_payload["x"]),
        y=int(bbox_payload["y"]),
        width=int(bbox_payload["w"]),
        height=int(bbox_payload["h"]),
    )

    return canonical_crop, canonical_bbox, str(payload["llm_label"])


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
            appearances=_serialize_appearances(annotated, decoded, settings),
            render_job_id=None,
        )
        return
    _fail_no_qualifying(api, decoded, settings, cost)


def _serialize_appearances(
    annotated: list,
    decoded: TrackJobMessage,
    settings: WorkerSettings,
) -> list[dict[str, Any]]:
    """Convert lib-level ``AnnotatedWindow`` to the api's
    ``_AppearancePayload`` shape (extra='forbid' — must match exactly).

    ``tracker_version`` is stamped from ``settings.tracker_version``
    (the version of the worker that ACTUALLY ran), not from
    ``decoded.tracker_version`` (the version that was current when
    the message was enqueued — possibly stale by hours if the queue
    backlog crossed a worker deploy). Mis-attributing rows breaks
    version-keyed cleanup in
    ``ProductAppearanceRepository.purge_for_catalog_and_tracker()``.

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
            "tracker_version": settings.tracker_version,
            "rejected_reason": w.rejected_reason,
        })
    return out


# ─── Phase 4 PR #5b — wizard scan_order parent flow ────────────────────
#
# The parent flow runs SAM2 + alignment over EVERY active catalog entry
# for the video, aggregates appearances tagged by catalog_entry_id, and
# /completes with render_job_id=None. Scoring + window-selection +
# stitch-plan-building happen later, per-child, in the API runner — the
# parent is GPU-only orchestration; the children are CPU-only render
# fan-out.
#
# Loose-coupling note: this function reuses the same pipeline-lib
# functions as the legacy flow (retrieve_candidate_scenes, propagate,
# assemble, annotate). The difference is the OUTER loop over catalog
# entries. We deliberately do NOT extract a shared "_process_one_product"
# helper in this PR — it would touch the legacy flow which is already
# in production. PR #6 can refactor once both paths are stable.


# Per-length min_window_duration_ms band table — codex Q4 correction.
# Threshold is a noise floor; it should scale with the signal floor.
# Values mirror plan §1.1 / §7.3.
_LENGTH_TO_MIN_WINDOW_MS: dict[int, int] = {
    15: 500, 30: 1000, 60: 1500, 90: 1500, 120: 1500,
}


def _min_window_ms_for_length(length_seconds: int) -> int:
    """Banded threshold per plan §7.3. Custom-input lengths clamp
    into the nearest band."""
    if length_seconds <= 15:
        return 500
    if length_seconds <= 30:
        return 1000
    return 1500


def _filter_scenes_by_time_range(
    scenes: list[dict[str, Any]],
    *,
    range_start_ms: int | None,
    range_end_ms: int | None,
    soft_padding_ms: int = 30_000,
) -> list[dict[str, Any]]:
    """Pre-filter scenes by time-range with soft padding (codex Q3).

    Returns the filtered scene-dict list (same shape as input, with
    only scenes whose ``[start_ms, end_ms]`` overlaps
    ``[range_start - pad, range_end + pad]``). If both bounds are
    None, returns the input list verbatim (no filtering).

    Returning the dicts (not just one map) lets the caller derive
    BOTH the keyframe map (``scene_id → keyframe_s3_key``) and the
    timing map (``scene_id → (start_ms, end_ms)``) from the same
    filtered set — important so coarse-retrieval candidates outside
    the user's time-range don't sneak through one map but get
    filtered by the other.

    The ±30s padding handles windows straddling the user's chosen
    boundary; the API's ``ck_psj_aggregate_output`` CHECK guarantees
    enough source range exists for at least one short per child even
    with padding.
    """
    if range_start_ms is None or range_end_ms is None:
        return list(scenes)
    padded_start = max(0, range_start_ms - soft_padding_ms)
    padded_end = range_end_ms + soft_padding_ms
    return [
        s
        for s in scenes
        if int(s.get("end_ms", 0)) > padded_start
        and int(s.get("start_ms", 0)) < padded_end
    ]


def _handle_scan_order_parent(
    *,
    decoded: TrackJobMessage,
    settings: WorkerSettings,
    api: ApiClient,
    s3: S3Client,
    embedder: SiglipEmbedder | None,
    tracker: Sam2Tracker | None,
    picker: SubsetPicker | None,
) -> None:
    """Wizard parent (``mode='scan_order'``) flow.

    Differs from the legacy single-product flow:

    1. Fetches the active catalog list (instead of a single entry).
    2. Loops over entries, running retrieve → propagate → assemble →
       alignment per-product.
    3. Aggregates appearances tagged by ``catalog_entry_id``.
    4. /complete with ``appearances`` + ``render_job_id=None`` —
       the API child runner picks up render_child rows (inserted
       atomically by the parent /complete fan-out hook in PR #116)
       and handles per-child scoring + stitching + render-enqueue.

    Per-product F4 counters (one set per entry) gate "stage-wide
    failure for THIS product" without killing the whole order. If
    every product F4-fails, the whole order /fails as
    ``tracker_low_confidence_global``.

    Time-range pre-filter (codex Q3) and per-length min-window
    threshold (plan §7.3) apply at the scenes/config layer before
    the per-product loop kicks off.

    Precondition: ``handle_track_job`` already issued the ``api.claim``
    call at the entrypoint. Re-claiming here would 409 (parent already
    in ``tracking``), then this function returned early, dispatch
    returned normally, the SDK ack-deleted the message — and the job
    never progressed past claim. Bug shipped 2026-05-03 with the
    wizard scan_order flow.
    """
    cost_accumulator = Decimal("0")
    length_seconds = decoded.length_seconds or 60

    # ── 1. heartbeat: resolving ───────────────────────────────
    api.heartbeat(
        job_id=decoded.job_id,
        claimed_by=settings.worker_id,
        stage="tracking",
        progress_pct=5,
        progress_label="resolving catalog",
        cost_delta_usd=Decimal("0"),
        lease_seconds=settings.worker_lease_seconds,
    )

    # ── 2. fetch active catalog ───────────────────────────────
    # When the wizard's product-select step picked a single entry,
    # narrow the fetch to that one (Pattern B endpoint
    # /internal/products/catalog/{id}). The per-product loop below
    # takes a uniform ``[entry, ...]`` shape, so wrapping in a
    # one-element list lets the rest of the function ignore the
    # distinction. service.enqueue_scan_order already validated, but
    # treat 404 here as the entry was rejected between submit and
    # worker pickup.
    if decoded.catalog_entry_id is not None:
        try:
            single = api.fetch_catalog_entry(
                catalog_entry_id=decoded.catalog_entry_id,
                org_id=decoded.org_id,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                api.fail(
                    job_id=decoded.job_id,
                    claimed_by=settings.worker_id,
                    cost_delta_usd=cost_accumulator,
                    error_code="no_products_detected",
                    error_message=(
                        f"catalog entry {decoded.catalog_entry_id} "
                        f"not found or rejected since submit"
                    ),
                )
                return
            raise
        catalog_entries = [single]
    else:
        catalog_entries = api.fetch_catalog_entries_for_video(
            video_id=decoded.video_id, org_id=decoded.org_id,
        )
    if not catalog_entries:
        api.fail(
            job_id=decoded.job_id,
            claimed_by=settings.worker_id,
            cost_delta_usd=cost_accumulator,
            error_code="no_products_detected",
            error_message=(
                "catalog has no active entries for this video; "
                "run enumeration first"
            ),
        )
        return

    # ── 3. fetch scenes-with-keyframes (ONCE for the video) ──
    api.heartbeat(
        job_id=decoded.job_id,
        claimed_by=settings.worker_id,
        stage="tracking",
        progress_pct=10,
        progress_label=f"fetching scenes for {len(catalog_entries)} products",
        cost_delta_usd=Decimal("0"),
        lease_seconds=settings.worker_lease_seconds,
    )
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
                    f"DriveFile {decoded.video_id} not found or not "
                    f"accessible to org {decoded.org_id}"
                ),
            )
            return
        raise
    scenes = scenes_resp.get("scenes", [])
    os_video_id = scenes_resp.get("video_id", "")

    # Single-proxy fast-fail: ``proxy_s3_key`` is None when transcode
    # hasn't completed for this video. Surface a distinct
    # ``proxy_missing`` error code so the wizard can show "video isn't
    # ready yet" rather than the generic ``internal_error``.
    proxy_s3_key = scenes_resp.get("proxy_s3_key")
    if not proxy_s3_key:
        api.fail(
            job_id=decoded.job_id,
            claimed_by=settings.worker_id,
            cost_delta_usd=cost_accumulator,
            error_code="proxy_missing",
            error_message=(
                f"DriveFile {decoded.video_id} has no proxy_s3_key — "
                f"transcode incomplete; retry once the video shows "
                f"as indexed."
            ),
        )
        return

    # ── 3.5 time-range pre-filter (codex Q3) ──────────────────
    filtered_scenes = _filter_scenes_by_time_range(
        scenes,
        range_start_ms=decoded.time_range_start_ms,
        range_end_ms=decoded.time_range_end_ms,
    )
    scene_id_to_kf = {
        s["scene_id"]: s["keyframe_s3_key"] for s in filtered_scenes
    }
    scene_id_to_timing: dict[str, tuple[int, int]] = {
        s["scene_id"]: (int(s["start_ms"]), int(s["end_ms"]))
        for s in filtered_scenes
    }
    if not scene_id_to_kf:
        api.fail(
            job_id=decoded.job_id,
            claimed_by=settings.worker_id,
            cost_delta_usd=cost_accumulator,
            error_code="tracker_low_confidence_global",
            error_message=(
                f"no scenes overlap the time-range "
                f"[{decoded.time_range_start_ms}, "
                f"{decoded.time_range_end_ms}]ms after soft-padding"
            ),
        )
        return

    # ── 4. per-product loop ───────────────────────────────────
    # Per-length threshold override (plan §7.3 — codex Q4).
    # ``TrackingConfig`` is a frozen dataclass — direct attribute
    # assignment raises ``FrozenInstanceError`` ("cannot assign to
    # field"). Use ``replace()`` to produce a new instance with the
    # one field overridden.
    cfg = replace(
        _make_config(settings),
        min_window_duration_ms=_min_window_ms_for_length(length_seconds),
    )

    progress_per_entry = 80.0 / max(len(catalog_entries), 1)
    aggregated_appearances: list[dict[str, Any]] = []
    products_succeeded = 0
    products_f4_failed = 0
    products_no_qualifying = 0

    # Download the full-video proxy ONCE for the whole order. Every
    # product's SAM2 pass reuses the same local file; the wrapper
    # seeks to per-scene windows in-memory. Tempdir is cleaned up
    # on context exit, including the F4-everywhere path where every
    # product raises.
    with downloaded_proxy(
        s3=s3,
        proxy_s3_key=proxy_s3_key,
        job_id_for_naming=str(decoded.job_id),
        expected_size_bytes=_resolve_proxy_size(s3, proxy_s3_key),
    ) as full_video_path_obj:
        full_video_path = str(full_video_path_obj)
        for i, entry in enumerate(catalog_entries):
            entry_id = UUID(str(entry["catalog_entry_id"]))
            entry_label = str(entry["llm_label"])
            progress_pct = 10 + int((i + 1) * progress_per_entry)
            try:
                api.heartbeat(
                    job_id=decoded.job_id,
                    claimed_by=settings.worker_id,
                    stage="tracking",
                    progress_pct=min(progress_pct, 89),
                    progress_label=(
                        f"tracking {entry_label} ({i+1}/{len(catalog_entries)})"
                    ),
                    cost_delta_usd=Decimal("0"),
                    lease_seconds=settings.worker_lease_seconds,
                )

                entry_appearances = _process_one_product_for_parent(
                    entry=entry,
                    scene_id_to_kf=scene_id_to_kf,
                    scene_id_to_timing=scene_id_to_timing,
                    full_video_path=full_video_path,
                    os_video_id=os_video_id,
                    cfg=cfg,
                    api=api,
                    s3=s3,
                    decoded=decoded,
                    settings=settings,
                    embedder=embedder,
                    tracker=tracker,
                )
                if entry_appearances is None:
                    # F4 stage-wide outage for THIS product. Don't kill
                    # the whole order — log + skip.
                    products_f4_failed += 1
                    continue
                if not entry_appearances:
                    products_no_qualifying += 1
                    continue
                aggregated_appearances.extend(entry_appearances)
                products_succeeded += 1
            except Exception as exc:
                logger.exception(
                    "scan_order_per_product_failed",
                    extra={
                        "job_id": str(decoded.job_id),
                        "catalog_entry_id": str(entry_id),
                        "entry_label": entry_label,
                    },
                )
                # Surface the exception type + message via worker_events
                # so failures are SQL-queryable without Aircloud logs.
                # Truncated to 1000 chars to respect the 16KB metadata
                # cap on the worker_events ingest endpoint.
                emit_event(
                    service="product-track-worker",
                    event_name="scan_order_per_product_failed",
                    category="job_failure",
                    level="ERROR",
                    org_id=str(decoded.org_id),
                    job_id=str(decoded.job_id),
                    video_id=decoded.video_id,
                    message=f"{type(exc).__name__}: {exc}"[:1000],
                    metadata={
                        "catalog_entry_id": str(entry_id),
                        "entry_label": entry_label,
                        "exception_type": type(exc).__name__,
                        "exception_message": str(exc)[:1000],
                    },
                )
                products_f4_failed += 1
                continue

    # ── 5. /complete or /fail ─────────────────────────────────
    if not aggregated_appearances:
        # Distinguish "all products F4-failed" (stage-wide regression)
        # from "all products produced no qualifying windows" (correct
        # behavior, just no good content).
        if products_f4_failed == len(catalog_entries):
            emit_event(
                service="product-track-worker",
                event_name="scan_order_all_products_f4_failed",
                category="job_failure",
                level="ERROR",
                org_id=str(decoded.org_id),
                job_id=str(decoded.job_id),
                video_id=decoded.video_id,
                message=(
                    f"all {len(catalog_entries)} products F4-failed; query "
                    f"worker_events WHERE job_id={decoded.job_id} for the "
                    f"per-product reasons (events scan_order_product_*_f4 "
                    f"and scan_order_per_product_failed carry the cause)."
                ),
                metadata={
                    "products_total": len(catalog_entries),
                    "products_succeeded": products_succeeded,
                    "products_no_qualifying": products_no_qualifying,
                    "products_f4_failed": products_f4_failed,
                },
            )
            api.fail(
                job_id=decoded.job_id,
                claimed_by=settings.worker_id,
                cost_delta_usd=cost_accumulator,
                error_code="internal_error",
                error_message=(
                    f"all {len(catalog_entries)} products F4-failed — "
                    f"likely a stage-wide regression (SigLIP2 / S3 / SAM2). "
                    f"Query worker_events WHERE job_id={decoded.job_id} "
                    f"for the per-product reasons."
                ),
            )
        else:
            api.fail(
                job_id=decoded.job_id,
                claimed_by=settings.worker_id,
                cost_delta_usd=cost_accumulator,
                error_code="tracker_low_confidence_global",
                error_message=(
                    f"no products produced qualifying windows "
                    f"(succeeded={products_succeeded}, "
                    f"no_qualifying={products_no_qualifying}, "
                    f"f4_failed={products_f4_failed})"
                ),
            )
        return

    logger.info(
        "scan_order_parent_completed",
        extra={
            "job_id": str(decoded.job_id),
            "products_total": len(catalog_entries),
            "products_succeeded": products_succeeded,
            "products_no_qualifying": products_no_qualifying,
            "products_f4_failed": products_f4_failed,
            "appearances_total": len(aggregated_appearances),
        },
    )
    # /complete with appearances + render_job_id=None — the parent's
    # /complete handler in the API routes through
    # transition_parent_to_fanned_out + create_render_children
    # (PR #116) atomically. Children are then picked up by the
    # API child runner (PR #117 stub; PR #6 real picker).
    api.complete_track(
        job_id=decoded.job_id,
        claimed_by=settings.worker_id,
        cost_delta_usd=cost_accumulator,
        appearances=aggregated_appearances,
        render_job_id=None,
    )


def _process_one_product_for_parent(
    *,
    entry: dict[str, Any],
    scene_id_to_kf: dict[str, str],
    scene_id_to_timing: dict[str, tuple[int, int]],
    full_video_path: str,
    os_video_id: str,
    cfg: TrackingConfig,
    api: ApiClient,
    s3: S3Client,
    decoded: TrackJobMessage,
    settings: WorkerSettings,
    embedder: SiglipEmbedder | None,
    tracker: Sam2Tracker | None,
) -> list[dict[str, Any]] | None:
    """Run retrieve → propagate → assemble → annotate for one
    catalog entry. Returns the appearances list (possibly empty) or
    ``None`` to signal stage-wide F4 failure for this product (the
    parent caller treats None as "skip this product").

    Per-entry F4 counters are scoped to this call — a stage-wide
    failure on one product doesn't poison the next product's run.
    """
    entry_id = UUID(str(entry["catalog_entry_id"]))
    entry_label = str(entry["llm_label"])

    # Fetch canonical crop bytes via the existing helper. Constructs
    # a synthetic TrackJobMessage shape so the helper signature stays
    # unchanged from the legacy flow.
    canonical_crop, canonical_bbox, llm_label = _fetch_canonical_crop(
        api=api,
        s3=s3,
        decoded=_TrackJobMessageWithCatalogEntryId(
            base=decoded, catalog_entry_id=entry_id,
        ),
        settings=settings,
    )

    # F4 wrappers — per-product so failures are isolated.
    embedder_impl = _CountingEmbedder(embedder or SiglipEmbedderImpl())
    coarse_client = CoarseRetrievalClientImpl(
        api=api,
        file_id=decoded.video_id,
        org_id=decoded.org_id,
        scene_id_to_timing=scene_id_to_timing,
    )
    keyframe_fetcher = _CountingKeyframeFetcher(
        KeyframeFetcherImpl(
            s3=s3,
            bucket=settings.drive_s3_bucket,
            scene_id_to_s3_key=scene_id_to_kf,
        )
    )

    candidate_scenes = retrieve_candidate_scenes(
        canonical_crop,
        video_id=os_video_id,
        embedder=embedder_impl,
        coarse_client=coarse_client,
        keyframe_fetcher=keyframe_fetcher,
        config=cfg,
    )

    if keyframe_fetcher.all_attempts_failed:
        logger.warning(
            "scan_order_product_keyframe_f4",
            extra={"entry_id": str(entry_id), "attempted": keyframe_fetcher.attempted},
        )
        emit_event(
            service="product-track-worker",
            event_name="scan_order_product_keyframe_f4",
            category="job_failure",
            level="WARNING",
            org_id=str(decoded.org_id),
            job_id=str(decoded.job_id),
            video_id=decoded.video_id,
            message=(
                f"every keyframe fetch raised for catalog_entry "
                f"{entry_id} ({entry_label}); attempted="
                f"{keyframe_fetcher.attempted}. Likely S3 outage, "
                f"wrong bucket, or MINIO_ENDPOINT regression."
            ),
            metadata={
                "entry_id": str(entry_id),
                "entry_label": entry_label,
                "attempted": keyframe_fetcher.attempted,
                "stage": "keyframe_fetch",
            },
        )
        return None
    if embedder_impl.per_scene_all_failed():
        logger.warning(
            "scan_order_product_siglip_f4",
            extra={
                "entry_id": str(entry_id),
                "attempted": embedder_impl.per_scene_attempted,
            },
        )
        emit_event(
            service="product-track-worker",
            event_name="scan_order_product_siglip_f4",
            category="job_failure",
            level="WARNING",
            org_id=str(decoded.org_id),
            job_id=str(decoded.job_id),
            video_id=decoded.video_id,
            message=(
                f"every per-scene SigLIP2 embed raised for catalog_entry "
                f"{entry_id} ({entry_label}); attempted="
                f"{embedder_impl.per_scene_attempted}. Likely a bad SigLIP2 "
                f"deploy or corrupted HF cache."
            ),
            metadata={
                "entry_id": str(entry_id),
                "entry_label": entry_label,
                "attempted": embedder_impl.per_scene_attempted,
                "stage": "siglip2_embed",
            },
        )
        return None

    if not candidate_scenes:
        # Not an F4 — the product just has no scenes that match.
        return []

    # SAM2 propagation per-product. Reuses the single full-video
    # proxy the parent already downloaded — the SAM2 wrapper seeks
    # to each scene window in-memory.
    tracker_impl = _CountingSam2Tracker(
        tracker or Sam2TrackerImpl(model_id=settings.sam2_model_id),
        job_id=str(decoded.job_id),
        org_id=str(decoded.org_id),
        video_id=str(decoded.video_id),
    )
    detections = propagate_within_candidate_scenes(
        candidates=candidate_scenes,
        canonical_bbox=canonical_bbox,
        tracker=tracker_impl,
        full_video_path=full_video_path,
        config=cfg,
    )
    if tracker_impl.all_attempts_failed:
        logger.warning(
            "scan_order_product_sam2_f4",
            extra={"entry_id": str(entry_id), "attempted": tracker_impl.attempted},
        )
        emit_event(
            service="product-track-worker",
            event_name="scan_order_product_sam2_f4",
            category="job_failure",
            level="WARNING",
            org_id=str(decoded.org_id),
            job_id=str(decoded.job_id),
            video_id=decoded.video_id,
            message=(
                f"every SAM2 track raised for catalog_entry {entry_id} "
                f"({entry_label}); attempted={tracker_impl.attempted}. "
                f"Likely SAM2 OOM, wrong checkpoint, or proxy decode "
                f"failure on every candidate scene."
            ),
            metadata={
                "entry_id": str(entry_id),
                "entry_label": entry_label,
                "attempted": tracker_impl.attempted,
                "stage": "sam2_track",
            },
        )
        return None

    assembled = assemble_windows(detections, config=cfg)
    if not assembled:
        return []

    # Fetch transcripts/OCR ONLY for assembled scenes — mirrors the
    # legacy flow's optimization to skip the API call for products
    # with no qualifying windows.
    all_assembled_scene_ids = sorted({w.scene_id for w in assembled})
    transcripts, ocr = _fetch_transcripts_ocr(
        api=api,
        file_id=decoded.video_id,
        org_id=decoded.org_id,
        scene_ids=all_assembled_scene_ids,
    )

    annotated = annotate_alignment(
        assembled,
        label=llm_label,
        transcripts=transcripts,
        ocr=ocr,
    )

    # Tag appearances with this product's catalog_entry_id for
    # the parent's /complete callback (the API's _AppearancePayload
    # extra='forbid' boundary requires explicit tagging when
    # mode='scan_order' — see PR #114's dispatch fix).
    return _serialize_parent_appearances(
        annotated, decoded, settings, entry_id,
    )


def _serialize_parent_appearances(
    annotated: list,
    decoded: TrackJobMessage,
    settings: WorkerSettings,
    catalog_entry_id: UUID,
) -> list[dict[str, Any]]:
    """Same as ``_serialize_appearances`` but tags each row with
    the parent-flow ``catalog_entry_id`` (legacy flow derives it
    from the job row server-side; scan_order parents must set it
    explicitly — see PR #114 §3.3 dispatch logic).
    """
    out = []
    for w in annotated:
        out.append({
            "catalog_entry_id": str(catalog_entry_id),
            "scene_id": w.scene_id,
            "window_start_ms": w.window_start_ms,
            "window_end_ms": w.window_end_ms,
            "avg_bbox_area_pct": w.avg_bbox_area_pct,
            "avg_confidence": w.avg_confidence,
            "has_narration_mention": w.has_narration_mention,
            "has_ocr_overlap": w.has_ocr_overlap,
            "co_appearing_catalog_entry_ids": [],
            "raw_bbox_track_s3_key": None,
            "tracker_version": settings.tracker_version,
            "rejected_reason": w.rejected_reason,
        })
    return out


@dataclass
class _TrackJobMessageWithCatalogEntryId:
    """Adapter for ``_fetch_canonical_crop`` so the helper's
    signature stays unchanged.

    The legacy flow's ``_fetch_canonical_crop`` reads
    ``decoded.catalog_entry_id`` directly. For the scan_order
    parent loop, the catalog_entry_id varies per iteration — this
    adapter wraps the parent's TrackJobMessage with a per-iteration
    catalog_entry_id without mutating the original.
    """
    base: TrackJobMessage
    catalog_entry_id: UUID

    def __getattr__(self, name: str) -> Any:
        # Delegate everything except ``catalog_entry_id`` to the base
        # message. ``catalog_entry_id`` is overridden via instance
        # attribute (set by dataclass), so __getattr__ only fires
        # for missing attributes (which means it's on base).
        return getattr(self.base, name)
