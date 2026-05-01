"""Bearer-authed HTTP client for the api endpoints the track worker
uses.

Three groups of endpoints:

1. **Worker callbacks** (mirrors product-enumerate-worker):
   * ``POST /internal/products/{job_id}/claim``
   * ``POST /internal/products/{job_id}/heartbeat``
   * ``POST /internal/products/{job_id}/complete``
   * ``POST /internal/products/{job_id}/fail``

2. **Phase 3b read endpoints** (added in livecommerce PR #110):
   * ``POST /internal/videos/{file_id}/scenes-by-visual-similarity``
     — OS coarse pre-filter for the tracker
   * ``POST /internal/videos/{file_id}/scenes-content``
     — bulk transcript + OCR fetch for alignment

3. **Phase 2.5a** (existing):
   * ``GET /internal/videos/{file_id}/scenes-with-keyframes``
     — scene metadata + keyframe S3 keys

All requests carry the shared internal Bearer token. F1 Phase 3
per-service identity is supported: when ``settings.internal_service_id``
is set, the worker sends ``X-Heimdex-Service-Id`` + the per-service
token; otherwise falls back to the legacy global bearer.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx

logger = logging.getLogger(__name__)


class ApiClient:
    def __init__(
        self,
        *,
        base_url: str,
        internal_api_key: str,
        timeout_sec: float = 60.0,
        service_id: str = "",
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not internal_api_key:
            raise ValueError("internal_api_key is required")
        self.base_url = base_url.rstrip("/")

        headers = {"Authorization": f"Bearer {internal_api_key}"}
        # F1 Phase 3: opt into per-service identity by setting the
        # service id on the worker's env. The api validates this
        # header against ``settings.internal_service_tokens``;
        # absence falls back to the legacy global bearer.
        if service_id:
            headers["X-Heimdex-Service-Id"] = service_id

        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_sec),
            headers=headers,
        )

    def close(self) -> None:
        self._client.close()

    # ====================================================================
    # Worker callbacks (job lifecycle)
    # ====================================================================

    def claim(
        self,
        *,
        job_id: UUID,
        claimed_by: str,
        next_stage: str,
        lease_seconds: int,
    ) -> dict[str, Any]:
        resp = self._client.post(
            f"{self.base_url}/internal/products/{job_id}/claim",
            json={
                "claimed_by": claimed_by,
                "next_stage": next_stage,
                "lease_seconds": lease_seconds,
            },
        )
        resp.raise_for_status()
        return resp.json()

    def heartbeat(
        self,
        *,
        job_id: UUID,
        claimed_by: str,
        stage: str,
        progress_pct: int,
        progress_label: str | None,
        cost_delta_usd: Decimal,
        lease_seconds: int,
    ) -> dict[str, Any]:
        resp = self._client.post(
            f"{self.base_url}/internal/products/{job_id}/heartbeat",
            json={
                "claimed_by": claimed_by,
                "stage": stage,
                "progress_pct": progress_pct,
                "progress_label": progress_label,
                "cost_delta_usd": str(cost_delta_usd),
                "lease_seconds": lease_seconds,
            },
        )
        resp.raise_for_status()
        return resp.json()

    def complete_track(
        self,
        *,
        job_id: UUID,
        claimed_by: str,
        cost_delta_usd: Decimal,
        appearances: list[dict[str, Any]],
        stitching_plan: dict[str, Any] | None,
        render_job_id: UUID | None,
    ) -> dict[str, Any]:
        """Terminal success for tracking jobs. ``stitching_plan`` and
        ``render_job_id`` may be None if no qualifying windows were
        found — in that case the api should NOT enqueue a render and
        the worker reports the job as no-op-complete (UI surfaces "no
        appearances found")."""
        resp = self._client.post(
            f"{self.base_url}/internal/products/{job_id}/complete",
            json={
                "claimed_by": claimed_by,
                "cost_delta_usd": str(cost_delta_usd),
                # Track jobs return appearances + stitch plan, NOT
                # catalog_entries (those came from the enumerate pass).
                "catalog_entries": [],
                "appearances": appearances,
                "stitching_plan": stitching_plan,
                "render_job_id": str(render_job_id) if render_job_id else None,
            },
        )
        resp.raise_for_status()
        return resp.json()

    def fail(
        self,
        *,
        job_id: UUID,
        claimed_by: str,
        cost_delta_usd: Decimal,
        error_code: str,
        error_message: str,
    ) -> None:
        resp = self._client.post(
            f"{self.base_url}/internal/products/{job_id}/fail",
            json={
                "claimed_by": claimed_by,
                "cost_delta_usd": str(cost_delta_usd),
                "error_code": error_code,
                "error_message": error_message,
            },
        )
        resp.raise_for_status()

    # ====================================================================
    # Phase 3b reads
    # ====================================================================

    def fetch_scenes_with_keyframes(
        self, *, file_id: UUID, org_id: UUID,
    ) -> dict[str, Any]:
        """Phase 2.5a — chronologically-ordered scenes + keyframe S3
        keys. Used by the worker to look up canonical_keyframe S3
        path for a scene_id."""
        resp = self._client.get(
            f"{self.base_url}/internal/videos/{file_id}/scenes-with-keyframes",
            headers={"X-Heimdex-Org-Id": str(org_id)},
        )
        resp.raise_for_status()
        return resp.json()

    def find_similar_scenes(
        self,
        *,
        file_id: UUID,
        org_id: UUID,
        query_vec: list[float],
        top_k: int,
        min_similarity: float,
    ) -> list[dict[str, Any]]:
        """Phase 3b — OS coarse pre-filter. Returns the raw
        ``scenes`` list (each with ``scene_id`` + ``similarity``)."""
        resp = self._client.post(
            f"{self.base_url}/internal/videos/{file_id}/scenes-by-visual-similarity",
            headers={"X-Heimdex-Org-Id": str(org_id)},
            json={
                "query_vec": query_vec,
                "top_k": top_k,
                "min_similarity": min_similarity,
            },
        )
        resp.raise_for_status()
        return resp.json().get("scenes", [])

    def fetch_scenes_content(
        self, *, file_id: UUID, org_id: UUID, scene_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Phase 3b — bulk transcript + OCR fetch by scene_id list."""
        resp = self._client.post(
            f"{self.base_url}/internal/videos/{file_id}/scenes-content",
            headers={"X-Heimdex-Org-Id": str(org_id)},
            json={"scene_ids": scene_ids},
        )
        resp.raise_for_status()
        return resp.json().get("scenes", [])
