import logging
import time
from dataclasses import dataclass, field
from typing import Any

import requests

logger = logging.getLogger(__name__)

_DEFAULT_MAX_RETRIES = 3
_DEFAULT_BACKOFF_BASE = 0.5
_DEFAULT_BACKOFF_MAX = 8.0
_DEFAULT_TIMEOUT = 30
_RETRYABLE_STATUS_CODES = frozenset({502, 503, 504, 429})


@dataclass
class YouTubeAPIClient:
    base_url: str
    api_key: str
    org_id: str
    max_retries: int = _DEFAULT_MAX_RETRIES
    backoff_base: float = _DEFAULT_BACKOFF_BASE
    backoff_max: float = _DEFAULT_BACKOFF_MAX
    timeout: int = _DEFAULT_TIMEOUT
    _session: requests.Session = field(default_factory=requests.Session, init=False, repr=False)

    def __post_init__(self) -> None:
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )

    def list_enabled_youtube_channels(self, *, org_id: str | None = None) -> list[dict[str, Any]]:
        url = f"{self.base_url.rstrip('/')}/internal/youtube/channels"
        data = self._request_with_retry("GET", url, org_id=org_id)
        return data.get("channels", [])

    def list_youtube_video_ids(
        self,
        *,
        channel_id: str,
        org_id: str | None = None,
    ) -> list[str]:
        url = f"{self.base_url.rstrip('/')}/internal/youtube/channels/{channel_id}/video_ids"
        data = self._request_with_retry("GET", url, org_id=org_id)
        return data.get("video_ids", [])

    def create_youtube_video(
        self,
        payload: dict[str, Any],
        *,
        org_id: str | None = None,
    ) -> dict[str, Any]:
        channel_id = payload.get("channel_id")
        if not channel_id:
            raise ValueError("payload.channel_id is required")
        body = {
            "youtube_video_id": payload.get("youtube_video_id"),
            "title": payload.get("title"),
            "duration_seconds": payload.get("duration_seconds"),
            "thumbnail_url": payload.get("thumbnail_url"),
            "description": payload.get("description"),
        }
        url = f"{self.base_url.rstrip('/')}/internal/youtube/channels/{channel_id}/videos"
        return self._request_with_retry("POST", url, json=body, org_id=org_id)

    def mark_youtube_channel_synced(
        self,
        *,
        channel_id: str,
        discovered_count: int,
        created_count: int,
        org_id: str | None = None,
    ) -> bool:
        url = f"{self.base_url.rstrip('/')}/internal/youtube/channels/{channel_id}/sync-complete"
        body = {
            "discovered_count": discovered_count,
            "created_count": created_count,
        }
        data = self._request_with_retry("PATCH", url, json=body, org_id=org_id)
        return data.get("ok", False)

    def update_youtube_video_status(
        self,
        video_pk: str,
        *,
        status: str,
        org_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}/internal/youtube/videos/{video_pk}/status"
        body: dict[str, Any] = {"processing_status": status, **kwargs}
        return self._request_with_retry("PATCH", url, json=body, org_id=org_id)

    def publish_youtube_transcode_job(
        self,
        payload: dict[str, Any],
        *,
        org_id: str | None = None,
    ) -> bool:
        url = f"{self.base_url.rstrip('/')}/internal/youtube/transcode"
        data = self._request_with_retry("POST", url, json=payload, org_id=org_id)
        return data.get("message_sent", False)

    def claim_pending_youtube_downloads(
        self,
        *,
        limit: int = 5,
        org_id: str | None = None,
    ) -> list[dict[str, Any]]:
        url = f"{self.base_url.rstrip('/')}/internal/youtube/videos/pending"
        data = self._request_with_retry("GET", url, params={"limit": limit}, org_id=org_id)
        return data.get("videos", [])

    def list_youtube_cleanup_candidates(self, *, org_id: str | None = None) -> list[dict[str, Any]]:
        url = f"{self.base_url.rstrip('/')}/internal/youtube/videos/cleanup-candidates"
        data = self._request_with_retry("GET", url, org_id=org_id)
        return data.get("videos", [])

    def mark_youtube_original_deleted(
        self,
        video_pk: str,
        *,
        original_deleted: bool = True,
        org_id: str | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}/internal/youtube/videos/{video_pk}/mark-deleted"
        body = {"original_deleted": original_deleted}
        return self._request_with_retry("PATCH", url, json=body, org_id=org_id)

    def _request_with_retry(self, method: str, url: str, *, org_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("timeout", self.timeout)
        request_headers = dict(kwargs.pop("headers", {}))
        request_headers["Authorization"] = f"Bearer {self.api_key}"
        request_headers["X-Heimdex-Org-Id"] = org_id or self.org_id
        kwargs["headers"] = request_headers

        last_exception: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.request(method, url, **kwargs)

                if resp.status_code < 300:
                    return resp.json()

                if resp.status_code in _RETRYABLE_STATUS_CODES:
                    last_exception = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:500]}")
                    if attempt < self.max_retries:
                        delay = self._backoff_delay(attempt)
                        logger.warning(
                            "youtube_internal_api_retryable_error",
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

                raise RuntimeError(f"Internal API error {resp.status_code}: {resp.text[:500]}")

            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exception = exc
                if attempt < self.max_retries:
                    delay = self._backoff_delay(attempt)
                    logger.warning(
                        "youtube_internal_api_connection_retry",
                        extra={
                            "method": method,
                            "url": url,
                            "error": str(exc),
                            "attempt": attempt + 1,
                            "retry_delay": delay,
                        },
                    )
                    time.sleep(delay)
                    continue

        raise RuntimeError(
            f"Internal API request failed after {self.max_retries + 1} attempts: {last_exception}"
        )

    def _backoff_delay(self, attempt: int) -> float:
        delay = self.backoff_base * (2 ** attempt)
        return min(delay, self.backoff_max)
