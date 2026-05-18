"""Per-job handler for ``product.enumerate_job`` messages.

Flow (per plan §6.1, mirrored in
``heimdex_media_pipelines.product_enum.pipeline.enumerate_products``):

    1. Claim the job → API marks ``stage=enumerating``, returns
       ``(org_id, video_id, duration_preset_sec)``.
    2. Heartbeat ``progress_pct=10`` while we resolve the scene list.
    3. Resolve scene metadata via the Phase 2.5a internal endpoint +
       download keyframes from S3.
    4. Heartbeat ``progress_pct=30`` while we run the LLM batches.
    5. Run :func:`enumerate_products` (LLM + SigLIP2 + cluster + filter).
    6. Upload canonical crops to
       ``s3://{bucket}/products/{org_id}/{video_id}/{uuid}.jpg``.
    7. POST ``/internal/products/{job_id}/complete`` with the catalog
       entry payload + accumulated cost.

Failures are caught at the dispatcher boundary; this module raises so
the dispatcher can map exceptions to the right ``error_code``.
"""

from __future__ import annotations

import io
import logging
import uuid as _uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

import httpx
from heimdex_media_pipelines.product_enum import (
    CanonicalProduct,
    EnumerationConfig,
    SceneKeyframe,
    enumerate_products,
)
from heimdex_media_pipelines.siglip2 import (
    SiglipConfig,
    embed_pil_image_batch,
    load as load_siglip,
)
from heimdex_worker_sdk.s3 import S3Client

from src.api_client import ApiClient
from src.openai_vlm import OpenAIVlmClient, VlmSchemaError, VlmTimeoutError
from src.settings import WorkerSettings

if TYPE_CHECKING:  # pragma: no cover
    from PIL import Image

logger = logging.getLogger(__name__)


@dataclass
class EnumerateJobMessage:
    """Decoded SQS body shape — matches
    ``heimdex_media_contracts.product.ProductEnumerateJob``."""

    job_id: UUID
    org_id: UUID
    video_id: UUID
    requested_by_user_id: UUID
    enumeration_version: str
    enumeration_prompt_version: str
    max_keyframes: int
    callback_base_url: str

    @classmethod
    def from_dict(cls, body: dict[str, Any]) -> "EnumerateJobMessage":
        return cls(
            job_id=UUID(body["job_id"]),
            org_id=UUID(body["org_id"]),
            video_id=UUID(body["video_id"]),
            requested_by_user_id=UUID(body["requested_by_user_id"]),
            enumeration_version=str(body["enumeration_version"]),
            enumeration_prompt_version=str(body["enumeration_prompt_version"]),
            max_keyframes=int(body.get("max_keyframes", 60)),
            # SECURITY (F3): tolerated-but-ignored. Future contract
            # bump should drop this field entirely.
            callback_base_url=str(body.get("callback_base_url", "")),
        )


def handle_enumerate_job(
    *,
    message: dict[str, Any],
    settings: WorkerSettings,
    vlm_client: OpenAIVlmClient,
) -> None:
    """Single-message dispatch entrypoint. Raises on any failure; the
    surrounding dispatcher converts exceptions to the matching
    ``error_code`` on the ``/fail`` callback.
    """
    decoded = EnumerateJobMessage.from_dict(message)
    # SECURITY (F3): the API base must come from worker settings only,
    # never from the queue body. ``decoded.callback_base_url`` is held
    # on the dataclass to mirror the contract but is deliberately
    # ignored here.
    api = ApiClient(
        base_url=settings.drive_api_base_url,
        internal_api_key=settings.drive_internal_api_key,
    )
    try:
        # 1. Claim
        # The api returns 409 for "already claimed / completed /
        # cancelled" — duplicate or stale SQS deliveries. Per api
        # contract: ack the message, do not retry. Pre-fix the 409
        # propagated to the dispatcher's generic exception path →
        # /fail attempt (also 409 — we don't own the lease) →
        # re-raise → eventual DLQ for what is a no-op.
        try:
            api.claim(
                job_id=decoded.job_id,
                claimed_by=settings.worker_id,
                next_stage="enumerating",
                lease_seconds=settings.worker_lease_seconds,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 409:
                logger.info(
                    "enumerate_claim_conflict_acking_message",
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

        # 2-3. Resolve scenes + download keyframes.
        api.heartbeat(
            job_id=decoded.job_id, claimed_by=settings.worker_id,
            stage="enumerating", progress_pct=10,
            progress_label="Resolving scenes",
            cost_delta_usd=Decimal("0"),
            lease_seconds=settings.worker_lease_seconds,
        )
        keyframes = _fetch_keyframes(
            settings=settings,
            org_id=decoded.org_id,
            video_id=decoded.video_id,
            max_keyframes=decoded.max_keyframes,
        )
        if not keyframes:
            api.fail(
                job_id=decoded.job_id, claimed_by=settings.worker_id,
                cost_delta_usd=Decimal("0"),
                error_code="video_not_found",
                error_message="no scenes / keyframes resolved for video",
            )
            return

        # 4. Run pipeline.
        api.heartbeat(
            job_id=decoded.job_id, claimed_by=settings.worker_id,
            stage="enumerating", progress_pct=30,
            progress_label=f"Enumerating ({len(keyframes)} keyframes)",
            cost_delta_usd=Decimal("0"),
            lease_seconds=settings.worker_lease_seconds,
        )
        siglip = load_siglip(SiglipConfig(model_id=settings.siglip2_model_id))
        config = EnumerationConfig(
            max_keyframes=decoded.max_keyframes,
            vlm_batch_size=settings.openai_batch_size,
            cluster_cosine_threshold=settings.enum_cluster_cosine_threshold,
            min_supporting_keyframes=settings.enum_min_supporting_keyframes,
            min_prominence_pct=settings.enum_prominence_floor_pct,
            min_enumeration_confidence=settings.enum_min_confidence,
            enumeration_version=decoded.enumeration_version,
        )
        try:
            # Prompts are ignored by ``OpenAIVlmClient`` in the OWLv2
            # two-stage refactor — the client owns its own label prompt
            # (``src.owlv2_prompts.LABEL_PROMPT_SYSTEM``) and OWLv2
            # takes a query list, not a free-form system prompt. We
            # pass empty strings to satisfy the protocol while keeping
            # the pipeline call site unchanged.
            products, total_cost = enumerate_products(
                keyframes=keyframes,
                vlm_client=vlm_client,
                embedder=lambda imgs: embed_pil_image_batch(imgs, loaded=siglip),
                system_prompt="",
                user_prompt_template="",
                config=config,
            )
        except VlmTimeoutError as exc:
            api.fail(
                job_id=decoded.job_id, claimed_by=settings.worker_id,
                cost_delta_usd=Decimal("0"),
                error_code="llm_timeout",
                error_message=str(exc)[:1900],
            )
            return
        except VlmSchemaError as exc:
            api.fail(
                job_id=decoded.job_id, claimed_by=settings.worker_id,
                cost_delta_usd=Decimal("0"),
                error_code="llm_schema_mismatch",
                error_message=str(exc)[:1900],
            )
            return

        # All-rejected != failure — we still post the rejected entries
        # so the API surfaces the empty-state UI honestly. But "0
        # candidate clusters at all" (e.g., LLM returned nothing) is a
        # legitimate failure.
        accepted = [p for p in products if p.rejected_reason is None]
        if not products:
            api.fail(
                job_id=decoded.job_id, claimed_by=settings.worker_id,
                cost_delta_usd=Decimal(str(total_cost)),
                error_code="no_products_detected",
                error_message="LLM enumeration produced 0 candidate clusters",
            )
            return

        # 5. Upload crops + build catalog payload.
        api.heartbeat(
            job_id=decoded.job_id, claimed_by=settings.worker_id,
            stage="enumerating", progress_pct=80,
            progress_label="Uploading reference crops",
            cost_delta_usd=Decimal(str(total_cost)),
            lease_seconds=settings.worker_lease_seconds,
        )
        catalog_entries = _upload_crops_and_build_payload(
            settings=settings,
            org_id=decoded.org_id,
            video_id=decoded.video_id,
            products=products,
            enumeration_version=decoded.enumeration_version,
            enumeration_prompt_version=decoded.enumeration_prompt_version,
        )

        # 6. Complete.
        api.complete_enumeration(
            job_id=decoded.job_id, claimed_by=settings.worker_id,
            cost_delta_usd=Decimal("0"),  # already reported in heartbeats
            catalog_entries=catalog_entries,
        )
        logger.info(
            "product_enumerate_completed",
            extra={
                "job_id": str(decoded.job_id),
                "candidate_count": len(products),
                "accepted_count": len(accepted),
                "cost_usd": float(total_cost),
            },
        )
    finally:
        api.close()


# ---------- I/O helpers (Phase 2.5b — wired) ----------

def _fetch_keyframes(
    *,
    settings: WorkerSettings,
    org_id: UUID,
    video_id: UUID,
    max_keyframes: int,
    s3_client: S3Client | None = None,
) -> list[SceneKeyframe]:
    """Resolve the scene list via the Phase 2.5a internal endpoint and
    download each scene's keyframe from S3 / MinIO.

    Returns ``[]`` if:
    * the API returns 404 (video not registered) — the caller maps
      this to ``error_code="video_not_found"``;
    * the API returns 0 scenes — same downstream effect;
    * every keyframe download fails — defensive (treats as
      ``video_not_found`` so the worker doesn't burn LLM budget on an
      empty input).

    Per-keyframe download failures (single object missing) are logged
    + skipped; one missing keyframe out of N must not abort the whole
    job. The pipeline tolerates a sparse keyframe set.
    """
    from PIL import Image

    s3 = s3_client if s3_client is not None else S3Client(
        bucket=settings.drive_s3_bucket,
    )

    # SECURITY (F3): URL base must come from worker settings only —
    # never from the queue body. Bearer header travels with this
    # request, so a body-controlled URL would be a credential exfil.
    base = settings.drive_api_base_url.rstrip("/")
    url = f"{base}/internal/videos/{video_id}/scenes-with-keyframes"
    headers = {
        "Authorization": f"Bearer {settings.drive_internal_api_key}",
        "X-Heimdex-Org-Id": str(org_id),
    }
    try:
        with httpx.Client(timeout=httpx.Timeout(30.0)) as client:
            resp = client.get(url, headers=headers)
        if resp.status_code == 404:
            logger.info(
                "fetch_keyframes_video_not_found",
                extra={"video_id": str(video_id)},
            )
            return []
        resp.raise_for_status()
    except httpx.HTTPError:
        logger.exception(
            "fetch_keyframes_http_error", extra={"video_id": str(video_id)},
        )
        return []

    body = resp.json()
    raw_scenes: list[dict[str, Any]] = body.get("scenes", [])
    if not raw_scenes:
        return []

    # Subsample evenly when the video has more scenes than the cap.
    # Pipeline.enumerate_products also subsamples, but doing it here
    # bounds S3 download cost (we don't fetch keyframes we'll discard).
    if len(raw_scenes) > max_keyframes:
        stride = len(raw_scenes) / max_keyframes
        sampled = [
            raw_scenes[int(i * stride)] for i in range(max_keyframes)
        ]
    else:
        sampled = raw_scenes

    keyframes: list[SceneKeyframe] = []
    for scene in sampled:
        s3_key = scene.get("keyframe_s3_key")
        scene_id = scene.get("scene_id")
        if not s3_key or not scene_id:
            continue
        raw = s3.get_object_bytes(s3_key)
        if raw is None:
            # ``get_object_bytes`` returns None on NoSuchKey or
            # transient errors (sdk-level retry already exhausted).
            # Skip and let the rest of the keyframes carry the job.
            logger.warning(
                "fetch_keyframes_missing_s3_object",
                extra={"video_id": str(video_id), "s3_key": s3_key},
            )
            continue
        try:
            image = Image.open(io.BytesIO(raw))
            image.load()  # force decode now so we surface PIL errors here
        except Exception:
            logger.warning(
                "fetch_keyframes_decode_failed",
                extra={"video_id": str(video_id), "s3_key": s3_key},
                exc_info=True,
            )
            continue
        # ``frame_idx`` semantically carries the keyframe's millisecond
        # timestamp. The contracts schema names it ``keyframe_frame_idx``
        # which is mildly misleading — see the schemas comment. Using
        # ms is acceptable because nothing downstream decodes by
        # absolute frame number.
        kf_ts = scene.get("keyframe_timestamp_ms") or 0
        keyframes.append(
            SceneKeyframe(
                scene_id=str(scene_id),
                frame_idx=int(kf_ts),
                image=image,
            )
        )

    return keyframes


def _upload_crops_and_build_payload(
    *,
    settings: WorkerSettings,
    org_id: UUID,
    video_id: UUID,
    products: list[CanonicalProduct],
    enumeration_version: str,
    enumeration_prompt_version: str,
    s3_client: S3Client | None = None,
) -> list[dict[str, Any]]:
    """Upload each product's canonical crop to S3 and build the
    catalog-entry payload for the API ``complete`` callback.

    The S3 key uses a worker-generated UUID (NOT the future API row
    id — the worker doesn't know that yet, and content-addressable
    schemes would entangle the storage path with detection drift).
    The catalog row's id is generated by Postgres on insert; the link
    between row and crop is via the persisted ``canonical_crop_s3_key``
    field.

    Payload shape MUST match
    ``app.modules.shorts_auto_product.internal_router._CatalogEntryPayload``
    exactly. Drift here = 400 on the complete callback.
    """
    s3 = s3_client if s3_client is not None else S3Client(
        bucket=settings.drive_s3_bucket,
    )

    payloads: list[dict[str, Any]] = []
    for product in products:
        crop_uuid = _uuid.uuid4()
        s3_key = f"products/{org_id}/{video_id}/{crop_uuid}.jpg"
        try:
            buf = io.BytesIO()
            product.canonical_crop.convert("RGB").save(
                buf, format="JPEG", quality=90, optimize=True,
            )
            buf.seek(0)
            s3._client.put_object(  # type: ignore[attr-defined]
                Bucket=s3.bucket,
                Key=s3_key,
                Body=buf.getvalue(),
                ContentType="image/jpeg",
            )
        except Exception:
            # Don't fail the entire job on a single upload — but we
            # MUST not include this entry in the payload (the API
            # would persist a row pointing at a missing object, which
            # is worse than dropping the product silently).
            logger.exception(
                "upload_canonical_crop_failed",
                extra={"video_id": str(video_id), "crop_uuid": str(crop_uuid)},
            )
            continue

        payloads.append({
            "canonical_crop_s3_key": s3_key,
            "canonical_video_id": str(video_id),
            "canonical_frame_idx": product.canonical_frame_idx,
            "canonical_bbox": {
                "x": int(product.canonical_bbox_xywh[0]),
                "y": int(product.canonical_bbox_xywh[1]),
                "w": int(product.canonical_bbox_xywh[2]),
                "h": int(product.canonical_bbox_xywh[3]),
            },
            "llm_label": product.llm_label,
            "siglip2_embedding": list(product.siglip2_embedding),
            "enumeration_confidence": float(product.enumeration_confidence),
            "prominence_score": float(product.prominence_score),
            "enumeration_version": enumeration_version,
            "enumeration_prompt_version": enumeration_prompt_version,
        })
    return payloads
