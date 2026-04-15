"""Per-message handler for blur layer export jobs.

Lifecycle for one ``blur.export_created`` SQS message:

    1. parse SQS body → export_id (the rest comes from /claim)
    2. POST /internal/blur/exports/{export_id}/claim → source proxy
       key + per-category mask subset + lease_token
    3. download source + every mask file from S3 to a temp dir
    4. FFmpeg compose → ProRes 4444 yuva444p10le ``.mov``
    5. upload to blur_exports/{video_id}/{export_id}/layer.mov
    6. POST /internal/blur/exports/{export_id}/complete with the S3 key
    7. on failure, complete() with status=failed + error string

CPU-bound: no torch, no GPU — ffmpeg only. Runs inside the same
drive-blur-worker container as the blur-job task but shares nothing
stateful with it. The two handlers are dispatched by message type and
are independently testable.
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

from src.tasks.ffmpeg_compose import run_compose

logger = logging.getLogger(__name__)


@dataclass
class BlurExportRef:
    """Lightweight SQS body envelope. Authoritative state comes from
    the API's claim response, not the message body.
    """

    export_id: UUID
    org_id: UUID
    blur_job_id: UUID
    video_id: str


def sqs_to_export_ref(message: Any) -> BlurExportRef:
    body_raw = message.body if hasattr(message, "body") else message["Body"]
    body = json.loads(body_raw) if isinstance(body_raw, str) else body_raw
    return BlurExportRef(
        export_id=UUID(body["export_id"]),
        org_id=UUID(body["org_id"]),
        blur_job_id=UUID(body["blur_job_id"]),
        video_id=body["video_id"],
    )


def _layer_s3_key(video_id: str, export_id: UUID) -> str:
    return f"blur_exports/{video_id}/{export_id}/layer.mov"


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


def process_export_message(
    *,
    api_base_url: str,
    internal_api_key: str,
    settings: Any,
    export_ref: BlurExportRef,
) -> None:
    """Handle one SQS ``blur.export_created`` message end-to-end."""
    from heimdex_worker_sdk.s3 import S3Client

    export_id = export_ref.export_id
    temp_dir = Path(tempfile.mkdtemp(prefix=f"blur_export_{export_id}_"))
    lease_token: str | None = None
    uploaded_key: str | None = None
    s3: Any = None

    try:
        # 1. Claim. The response carries the authoritative source key,
        #    the category subset of parent masks, and a fresh lease
        #    token. Anything in the SQS body is advisory only.
        resp = _post(
            api_base_url, internal_api_key,
            f"/internal/blur/exports/{export_id}/claim",
        )
        if resp.status_code == 409:
            logger.info(
                "blur_export_claim_skipped",
                extra={"export_id": str(export_id), "body": resp.text[:200]},
            )
            return
        if resp.status_code == 404:
            logger.warning(
                "blur_export_claim_not_found",
                extra={"export_id": str(export_id)},
            )
            return
        resp.raise_for_status()
        claim = resp.json()
        lease_token = claim["lease_token"]
        source_key: str = claim["source_s3_key"]
        mask_keys: dict[str, str] = claim["mask_s3_keys"] or {}
        categories: list[str] = list(claim["categories"])
        if not mask_keys:
            raise RuntimeError("claim response has empty mask_s3_keys")

        # 2. Download source + every selected mask to temp dir.
        s3 = S3Client(bucket=settings.drive_s3_bucket)
        source_path = temp_dir / "source.mp4"
        s3.download_file(source_key, source_path)

        # Preserve category order so the resulting filter_complex is
        # deterministic across runs (helps reproducibility + debug).
        ordered_masks: list[tuple[str, Path]] = []
        for category in categories:
            key = mask_keys.get(category)
            if key is None:
                raise RuntimeError(
                    f"claim response missing mask for category {category!r}"
                )
            local = temp_dir / "masks" / f"{category}.mkv"
            s3.download_file(key, local)
            ordered_masks.append((category, local))

        # 3. Compose. ffmpeg runs synchronously; the lease is refreshed
        #    by the heartbeat-via-visibility behavior of SQSConsumerLoop,
        #    not by a ping from this task. If composition blows the
        #    lease the watchdog will reap the row.
        layer_path = temp_dir / "layer.mov"
        run_compose(
            source_path=source_path,
            mask_paths=[p for _, p in ordered_masks],
            output_path=layer_path,
        )

        # 4. Upload the composed layer under the per-export prefix so
        #    S3 lifecycle reaps it independently of the parent blur job.
        uploaded_key = _layer_s3_key(export_ref.video_id, export_id)
        s3.upload_file(layer_path, uploaded_key)

        # 5. Complete.
        complete_resp = _post(
            api_base_url, internal_api_key,
            f"/internal/blur/exports/{export_id}/complete",
            {
                "lease_token": lease_token,
                "status": "done",
                "layer_s3_key": uploaded_key,
            },
        )
        complete_resp.raise_for_status()
        body_json = complete_resp.json()

        if body_json.get("reason") == "cancelled" and body_json.get("cleanup_required"):
            logger.info(
                "blur_export_cleanup_after_cancel",
                extra={"export_id": str(export_id)},
            )
            try:
                s3.delete(uploaded_key)
            except Exception:
                logger.exception(
                    "blur_export_post_cancel_cleanup_failed",
                    extra={"export_id": str(export_id), "key": uploaded_key},
                )

        logger.info(
            "blur_export_processed",
            extra={
                "export_id": str(export_id),
                "video_id": export_ref.video_id,
                "mask_count": len(ordered_masks),
                "categories": categories,
                "layer_key": uploaded_key,
            },
        )

    except Exception as exc:
        logger.exception(
            "blur_export_failed",
            extra={
                "export_id": str(export_id),
                "error": f"{type(exc).__name__}: {exc}",
            },
        )
        # Best-effort mark failed so the customer isn't stuck at
        # "queued" forever. If the API call also fails, the SQS
        # message will redeliver and the next worker will see the row
        # still running with an expired lease.
        if lease_token is not None:
            try:
                _post(
                    api_base_url, internal_api_key,
                    f"/internal/blur/exports/{export_id}/complete",
                    {
                        "lease_token": lease_token,
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {str(exc)[:500]}",
                    },
                )
            except Exception:
                logger.exception(
                    "blur_export_complete_on_failure_failed",
                    extra={"export_id": str(export_id)},
                )
        # Also best-effort clean up any orphan S3 upload so a failed
        # export doesn't leave a dangling layer under the expired row.
        if uploaded_key is not None and s3 is not None:
            try:
                s3.delete(uploaded_key)
            except Exception:
                logger.exception(
                    "blur_export_orphan_cleanup_failed",
                    extra={"export_id": str(export_id), "key": uploaded_key},
                )
        raise
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


__all__ = [
    "BlurExportRef",
    "process_export_message",
    "sqs_to_export_ref",
]
