"""
Aircloud External API client for GPU worker lifecycle management.

Thin HTTP wrapper over the Aircloud External API (start/stop/scale/status).
Used by:
  - sqs_producer.py (API): wake up workers when publishing SQS jobs
  - gpu_orchestrator.py (drive-worker): shut down idle workers periodically

All methods are synchronous and fire-and-forget safe.  Errors are logged,
never raised to callers (unless explicitly requested via raise_on_error).

API docs: https://external.aieev.cloud:5007/external/api/v1
Auth: Bearer token via API key generated in Aircloud web console.
"""

import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://external.aieev.cloud:5007/external/api/v1"
_DEFAULT_TIMEOUT = 10  # seconds


@dataclass(frozen=True)
class EndpointStatus:
    """Parsed response from GET /endpoints/{endpoint_id}."""

    endpoint_id: str
    name: str
    is_active: bool
    num_replicas: int
    replica_status_summary: dict[str, int]
    enable_autoscaling: bool
    instance_type_name: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EndpointStatus":
        return cls(
            endpoint_id=data.get("endpoint_id", ""),
            name=data.get("name", ""),
            is_active=data.get("is_active", False),
            num_replicas=data.get("num_replicas", 0),
            replica_status_summary=data.get("replica_status_summary", {}),
            enable_autoscaling=data.get("enable_autoscaling", False),
            instance_type_name=data.get("instance_type_name", ""),
        )


class AircloudClient:
    """Synchronous HTTP client for the Aircloud External API.

    Args:
        api_key: Bearer token for authentication.
        base_url: API base URL (default: production Aircloud endpoint).
        timeout: Request timeout in seconds.
        max_retries: Number of retries on transient failures (5xx, connection errors).
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: int = _DEFAULT_TIMEOUT,
        max_retries: int = 2,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
        )

        retry = Retry(
            total=max_retries,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    # ── Public API ─────────────────────────────────────────────────

    def get_status(self, endpoint_id: str) -> Optional[EndpointStatus]:
        """Get current endpoint status.  Returns None on failure."""
        try:
            resp = self._session.get(
                f"{self._base_url}/endpoints/{endpoint_id}",
                timeout=self._timeout,
            )
            resp.raise_for_status()
            return EndpointStatus.from_dict(resp.json())
        except Exception:
            logger.exception(
                "aircloud_get_status_failed",
                extra={"endpoint_id": endpoint_id},
            )
            return None

    def start(self, endpoint_id: str) -> bool:
        """Start an inactive endpoint.  Returns True on success.

        Idempotent: starting an already-active endpoint is a no-op on
        the Aircloud side (returns success).
        """
        try:
            resp = self._session.post(
                f"{self._base_url}/endpoints/{endpoint_id}/start",
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info(
                "aircloud_endpoint_started",
                extra={
                    "endpoint_id": endpoint_id,
                    "is_active": data.get("is_active"),
                    "message": data.get("message", ""),
                },
            )
            return True
        except Exception:
            logger.exception(
                "aircloud_start_failed",
                extra={"endpoint_id": endpoint_id},
            )
            return False

    def stop(self, endpoint_id: str) -> bool:
        """Stop an active endpoint.  Returns True on success."""
        try:
            resp = self._session.post(
                f"{self._base_url}/endpoints/{endpoint_id}/stop",
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info(
                "aircloud_endpoint_stopped",
                extra={
                    "endpoint_id": endpoint_id,
                    "is_active": data.get("is_active"),
                    "message": data.get("message", ""),
                },
            )
            return True
        except Exception:
            logger.exception(
                "aircloud_stop_failed",
                extra={"endpoint_id": endpoint_id},
            )
            return False

    def scale(self, endpoint_id: str, num_replicas: int) -> bool:
        """Scale replicas for an active endpoint.  Returns True on success.

        Requires autoscaling to be DISABLED on the Aircloud web console.
        """
        try:
            resp = self._session.post(
                f"{self._base_url}/endpoints/{endpoint_id}/scale",
                json={"num_replicas": num_replicas},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info(
                "aircloud_endpoint_scaled",
                extra={
                    "endpoint_id": endpoint_id,
                    "previous_replicas": data.get("previous_replicas"),
                    "current_replicas": data.get("current_replicas"),
                    "message": data.get("message", ""),
                },
            )
            return True
        except Exception:
            logger.exception(
                "aircloud_scale_failed",
                extra={
                    "endpoint_id": endpoint_id,
                    "num_replicas": num_replicas,
                },
            )
            return False
