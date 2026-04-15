"""Per-message handler for the blur SQS queue.

Lifecycle for one message:
    1. parse SQS body → BlurJobCreated (contracts)
    2. claim the job via POST /internal/blur/{id}/claim (atomic queued→running)
       * on 409 → message was cancelled or already claimed; delete + return
    3. download source mp4 from S3 to a temp dir
    4. run BlurPipeline.process_video → BlurResult
    5. upload blurred mp4 + manifest.json to per-job S3 prefix
    6. POST /internal/blur/{id}/complete with lease_token + result
       * if the API responds `cleanup_required` (job was cancelled mid-run),
         delete the just-uploaded S3 objects and return

Every exit path deletes the temp dir. The SQS message is deleted by the
consumer loop on a successful return; raising lets SQS redeliver.
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import requests

logger = logging.getLogger(__name__)


@dataclass
class BlurClaimRef:
    """Lightweight envelope — just what's needed to call /claim.

    The full source / options come back from the API on successful claim,
    not from the SQS message. That guarantees the worker always acts on
    the row's authoritative state, not a stale message body.
    """

    job_id: UUID
    org_id: UUID
    file_id: UUID
    video_id: str


def sqs_to_blur_claim(message: Any) -> BlurClaimRef:
    """Parse an SQS message body into a ``BlurClaimRef``."""
    body_raw = message.body if hasattr(message, "body") else message["Body"]
    body = json.loads(body_raw) if isinstance(body_raw, str) else body_raw
    return BlurClaimRef(
        job_id=UUID(body["job_id"]),
        org_id=UUID(body["org_id"]),
        file_id=UUID(body["file_id"]),
        video_id=body["video_id"],
    )


def _blurred_s3_key(video_id: str, job_id: UUID) -> str:
    # Per-job prefix: deleting one job's output never touches another.
    return f"blurred/{video_id}/{job_id}/blurred.mp4"


def _manifest_s3_key(video_id: str, job_id: UUID) -> str:
    return f"blurred/{video_id}/{job_id}/manifest.json"


def _mask_s3_key(video_id: str, job_id: UUID, category: str) -> str:
    # Per-job subdirectory matches the BlurResult.mask_paths layout
    # the pipeline writes to disk (``<mask_dir>/<category>.mkv``). The
    # export worker downloads these verbatim under the same keys.
    return f"blurred/{video_id}/{job_id}/masks/{category}.mkv"


def _make_progress_callback(
    api_base_url: str,
    internal_api_key: str,
    job_id: UUID,
    lease_token: str,
) -> Any:
    """Return a progress callback that forwards pipeline events to the
    API's internal heartbeat endpoint.

    The pipeline throttles events upstream (max ~1/sec or ~1 pct delta),
    so this posts at a modest rate. Failures are swallowed — a broken
    network during a heartbeat must not crash the frame loop.
    """
    endpoint = api_base_url.rstrip("/") + f"/internal/blur/{job_id}/progress"
    headers = _headers(internal_api_key)

    def _callback(event: Any) -> None:
        payload = {
            "lease_token": lease_token,
            "progress_pct": float(event.progress_pct),
            "phase": event.phase,
        }
        if event.message:
            payload["message"] = event.message
        try:
            requests.post(endpoint, headers=headers, data=json.dumps(payload), timeout=5.0)
        except Exception:
            logger.warning(
                "blur_progress_post_failed",
                extra={"job_id": str(job_id), "phase": event.phase},
            )

    return _callback


def _headers(internal_api_key: str) -> dict[str, str]:
    return {
        "X-Internal-Token": internal_api_key,
        "Content-Type": "application/json",
    }


def _post(
    api_base_url: str,
    internal_api_key: str,
    path: str,
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> requests.Response:
    url = api_base_url.rstrip("/") + path
    return requests.post(
        url,
        headers=_headers(internal_api_key),
        data=json.dumps(body or {}),
        timeout=timeout,
    )


def process_blur_message(
    *,
    api_base_url: str,
    internal_api_key: str,
    settings: Any,
    claim_ref: BlurClaimRef,
    pipeline: Any,
) -> None:
    """Handle one SQS blur message end-to-end."""
    from heimdex_worker_sdk.s3 import S3Client

    job_id = claim_ref.job_id
    temp_dir = Path(tempfile.mkdtemp(prefix=f"blur_{job_id}_"))

    try:
        # 1. Claim the job.
        resp = _post(
            api_base_url, internal_api_key,
            f"/internal/blur/{job_id}/claim",
        )
        if resp.status_code == 409:
            logger.info(
                "blur_claim_skipped",
                extra={"job_id": str(job_id), "body": resp.text[:200]},
            )
            return
        if resp.status_code == 404:
            logger.warning("blur_claim_not_found", extra={"job_id": str(job_id)})
            return
        resp.raise_for_status()
        claim = resp.json()
        lease_token = claim["lease_token"]
        source_key = claim["source_s3_key"]
        options = claim.get("options") or {}

        # 2. Download source.
        s3 = S3Client(bucket=settings.drive_s3_bucket)
        src_path = temp_dir / "input.mp4"
        s3.download_file(source_key, src_path)

        # 3. Run the pipeline.
        out_path = temp_dir / "blurred.mp4"
        mask_dir = temp_dir / "masks"
        # Re-apply per-request options onto the warm pipeline's config.
        # A cleaner design would pass a fresh BlurConfig per call, but
        # BlurPipeline.process_video does not currently accept one
        # (it uses ``self._config``), and mutating the warm singleton's
        # config is thread-safe under drive_blur_concurrency=1 which is
        # the only supported mode. A follow-up PR can move to
        # per-call config when we lift concurrency > 1.
        _apply_options_to_pipeline(pipeline, options)
        # Turn on per-category FFV1 mask emission and wire a live
        # progress heartbeat that POSTs to the API's internal progress
        # endpoint. Both are v0.10+ additions; they're safe to enable
        # unconditionally because the pipeline tolerates ffmpeg being
        # absent only at mask-open time, and drive-blur-worker's
        # Docker image bundles ffmpeg.
        pipeline.config.emit_masks = True
        pipeline.config.mask_dir = mask_dir
        pipeline.config.progress_callback = _make_progress_callback(
            api_base_url, internal_api_key, job_id, lease_token,
        )
        result = pipeline.process_video(src_path, out_path)

        # 4. Upload outputs under the per-job prefix.
        blurred_key = _blurred_s3_key(claim_ref.video_id, job_id)
        manifest_key = _manifest_s3_key(claim_ref.video_id, job_id)
        s3.upload_file(out_path, blurred_key)

        mask_s3_keys: dict[str, str] = {}
        for category, local_path in (result.mask_paths or {}).items():
            if not local_path or not Path(local_path).exists():
                continue
            mask_key = _mask_s3_key(claim_ref.video_id, job_id, category)
            s3.upload_file(local_path, mask_key)
            mask_s3_keys[category] = mask_key

        # Inject the freshly uploaded per-category mask S3 keys into
        # the manifest dict *before* serializing it, so the S3-stored
        # manifest.json is self-describing. The pipeline populates the
        # placeholder as None; we overwrite it with the real keys.
        manifest_dict = result.to_manifest()
        if mask_s3_keys:
            manifest_dict["mask_s3_keys"] = mask_s3_keys

        manifest_bytes = json.dumps(manifest_dict).encode()
        s3._client.put_object(  # private attr — matches face-worker pattern
            Bucket=s3.bucket,
            Key=manifest_key,
            Body=manifest_bytes,
            ContentType="application/json",
        )

        # 5. Complete.
        complete_payload: dict[str, Any] = {
            "lease_token": lease_token,
            "status": "done",
            "blurred_s3_key": blurred_key,
            "manifest_s3_key": manifest_key,
            "detections_summary": result.summary(),
        }
        if mask_s3_keys:
            complete_payload["mask_s3_keys"] = mask_s3_keys
        complete_resp = _post(
            api_base_url, internal_api_key,
            f"/internal/blur/{job_id}/complete",
            complete_payload,
        )
        complete_resp.raise_for_status()
        body_json = complete_resp.json()

        # If the API says the job was cancelled mid-run, the worker must
        # delete its own outputs — the user explicitly asked for no
        # artifact to exist. Include the per-category masks.
        if body_json.get("reason") == "cancelled" and body_json.get("cleanup_required"):
            logger.info(
                "blur_cleanup_after_cancel",
                extra={"job_id": str(job_id)},
            )
            keys_to_remove: list[str] = [blurred_key, manifest_key]
            keys_to_remove.extend(mask_s3_keys.values())
            for key in keys_to_remove:
                try:
                    s3.delete(key)
                except Exception:
                    logger.exception(
                        "blur_post_cancel_cleanup_failed",
                        extra={"job_id": str(job_id), "key": key},
                    )

        logger.info(
            "blur_job_processed",
            extra={
                "job_id": str(job_id),
                "video_id": claim_ref.video_id,
                "frames": result.frame_count,
                "total_ms": int(result.total_ms),
                "owl_infer_ms": int(result.owl_infer_ms),
                "summary": result.summary(),
            },
        )

    except Exception as exc:
        # Best-effort failure report. If the complete call itself fails
        # the SQS message will redeliver — the next attempt will see the
        # row still in ``running`` with an expired lease and can take it
        # over.
        logger.exception(
            "blur_job_failed",
            extra={"job_id": str(job_id), "error": f"{type(exc).__name__}: {exc}"},
        )
        try:
            if "lease_token" in locals():
                _post(
                    api_base_url, internal_api_key,
                    f"/internal/blur/{job_id}/complete",
                    {
                        "lease_token": lease_token,  # type: ignore[name-defined]
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {str(exc)[:500]}",
                    },
                )
        except Exception:
            logger.exception(
                "blur_complete_on_failure_failed",
                extra={"job_id": str(job_id)},
            )
        raise
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _apply_options_to_pipeline(pipeline: Any, options: dict[str, Any]) -> None:
    """Override a subset of BlurConfig fields on the warm pipeline.

    Kept minimal on purpose — the only fields that must be per-request
    are the ones that affect *what* gets blurred (categories, thresholds,
    stride). Model id / device must stay identical because switching
    them would require reloading OWLv2.
    """
    cfg = pipeline.config
    for field in (
        "do_faces", "do_owl", "owl_stride", "owl_score_threshold",
        "min_face_confidence", "mosaic_cells", "feather",
    ):
        if field in options:
            setattr(cfg, field, options[field])
    if "categories" in options:
        cats = options["categories"]
        cfg.categories = tuple(cats) if isinstance(cats, list) else cats
