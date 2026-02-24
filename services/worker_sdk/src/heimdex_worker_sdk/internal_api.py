"""
HTTP client for internal drive API endpoints.

Replaces direct database access in workers. Communicates with the API
server via /internal/drive/* endpoints using a pre-shared API key.

Features:
- Bounded retry with exponential backoff for transient failures (5xx, timeouts)
- Typed return values matching the API response schemas
- Single requests.Session for connection reuse
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import UUID

import requests

logger = logging.getLogger(__name__)

# Retry config defaults
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_BACKOFF_BASE = 0.5  # seconds
_DEFAULT_BACKOFF_MAX = 8.0   # seconds
_DEFAULT_TIMEOUT = 30        # seconds per request

# Retryable HTTP status codes
_RETRYABLE_STATUS_CODES = frozenset({502, 503, 504, 429})


@dataclass(frozen=True)
class ClaimedFile:
    """Represents a claimed drive file returned from the API."""
    id: UUID
    org_id: UUID
    video_id: str
    keyframe_s3_prefix: Optional[str] = None
    audio_s3_key: Optional[str] = None


@dataclass
class InternalAPIClient:
    """HTTP client for /internal/drive/* endpoints.

    Args:
        base_url: API server base URL (e.g. "http://api:8000")
        api_key: Pre-shared DRIVE_INTERNAL_API_KEY
        max_retries: Maximum retry attempts for transient failures
        backoff_base: Initial backoff delay in seconds
        backoff_max: Maximum backoff delay in seconds
        timeout: Request timeout in seconds
    """

    base_url: str
    api_key: str
    max_retries: int = _DEFAULT_MAX_RETRIES
    backoff_base: float = _DEFAULT_BACKOFF_BASE
    backoff_max: float = _DEFAULT_BACKOFF_MAX
    timeout: int = _DEFAULT_TIMEOUT
    _session: requests.Session = field(default_factory=requests.Session, init=False, repr=False)

    def __post_init__(self) -> None:
        self._session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })

    def claim_jobs(self, job_type: str, limit: int = 1) -> list[ClaimedFile]:
        """Claim pending enrichment jobs from the API.

        Returns a list of claimed files (may be empty if none available).
        """
        url = f"{self.base_url.rstrip('/')}/internal/drive/jobs/claim"
        payload = {"job_type": job_type, "limit": limit}

        data = self._request_with_retry("POST", url, json=payload)

        return [
            ClaimedFile(
                id=UUID(f["id"]),
                org_id=UUID(f["org_id"]),
                video_id=f["video_id"],
                keyframe_s3_prefix=f.get("keyframe_s3_prefix"),
                audio_s3_key=f.get("audio_s3_key"),
            )
            for f in data.get("files", [])
        ]

    def update_job_status(
        self,
        file_id: UUID,
        *,
        job_type: str,
        status: str,
        error: Optional[str] = None,
    ) -> bool:
        """Update enrichment status for a file.

        Args:
            file_id: Drive file UUID.
            job_type: One of 'caption', 'stt', 'ocr'.
            status: One of 'done', 'failed'.
            error: Optional error description (max 2000 chars).
        Returns True on success.
        """
        url = f"{self.base_url.rstrip('/')}/internal/drive/jobs/{file_id}/status"
        payload: dict[str, Any] = {"job_type": job_type, "status": status}
        if error is not None:
            payload["error"] = error
        data = self._request_with_retry("PATCH", url, json=payload)
        return data.get("ok", False)

    def get_file(self, file_id: UUID) -> dict[str, Any]:
        """Fetch file metadata for processing.

        Returns dict with id, org_id, video_id, keyframe_s3_prefix, and status fields.
        """
        url = f"{self.base_url.rstrip('/')}/internal/drive/files/{file_id}"
        return self._request_with_retry("GET", url)

    def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute HTTP request with bounded exponential backoff retry.

        Retries on:
        - Connection errors (requests.ConnectionError)
        - Timeouts (requests.Timeout)
        - Server errors (502, 503, 504, 429)

        Does NOT retry on:
        - 4xx client errors (400, 401, 404, 422)
        - Successful responses (2xx)
        """
        kwargs.setdefault("timeout", self.timeout)
        last_exception: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.request(method, url, **kwargs)

                if resp.status_code < 300:
                    return resp.json()

                if resp.status_code in _RETRYABLE_STATUS_CODES:
                    last_exception = RuntimeError(
                        f"HTTP {resp.status_code}: {resp.text[:500]}"
                    )
                    if attempt < self.max_retries:
                        delay = self._backoff_delay(attempt)
                        logger.warning(
                            "internal_api_retryable_error",
                            extra={
                                "method": method,
                                "url": url,
                                "status": resp.status_code,
                                "attempt": attempt + 1,
                                "retry_delay": delay,
                            },
                        )
                        time.sleep(delay)
                        continue

                # Non-retryable HTTP error — raise immediately
                raise RuntimeError(
                    f"Internal API error {resp.status_code}: {resp.text[:500]}"
                )

            except (requests.ConnectionError, requests.Timeout) as e:
                last_exception = e
                if attempt < self.max_retries:
                    delay = self._backoff_delay(attempt)
                    logger.warning(
                        "internal_api_connection_retry",
                        extra={
                            "method": method,
                            "url": url,
                            "error": str(e),
                            "attempt": attempt + 1,
                            "retry_delay": delay,
                        },
                    )
                    time.sleep(delay)
                    continue

        # All retries exhausted
        raise RuntimeError(
            f"Internal API request failed after {self.max_retries + 1} attempts: {last_exception}"
        )

    def _backoff_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay with cap."""
        delay = self.backoff_base * (2 ** attempt)
        return min(delay, self.backoff_max)
