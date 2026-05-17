"""Bearer-authed HTTP client for ``/internal/products/{job_id}/*``.

Thin wrapper around httpx — each method maps 1:1 to an internal
endpoint defined in
``services/api/app/modules/shorts_auto_product/internal_router.py``.
The worker uses these to claim jobs, heartbeat progress, and report
terminal results.

All requests carry the shared internal Bearer token (the same secret
the blur worker uses).
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
        timeout_sec: float = 30.0,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not internal_api_key:
            raise ValueError("internal_api_key is required")
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_sec),
            headers={"Authorization": f"Bearer {internal_api_key}"},
        )

    def close(self) -> None:
        self._client.close()

    # ---------- claim ----------

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

    # ---------- heartbeat ----------

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

    # ---------- complete (enumeration) ----------

    def complete_enumeration(
        self,
        *,
        job_id: UUID,
        claimed_by: str,
        cost_delta_usd: Decimal,
        catalog_entries: list[dict[str, Any]],
    ) -> dict[str, Any]:
        resp = self._client.post(
            f"{self.base_url}/internal/products/{job_id}/complete",
            json={
                "claimed_by": claimed_by,
                "cost_delta_usd": str(cost_delta_usd),
                "catalog_entries": catalog_entries,
                "appearances": [],
                "render_job_id": None,
            },
        )
        resp.raise_for_status()
        return resp.json()

    # ---------- fail ----------

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
