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
    lease_token: Optional[str] = None
    lease_expires_at: Optional[str] = None


@dataclass(frozen=True)
class ClaimedConnection:
    """Represents a claimed drive connection returned from the sync API."""

    connection_id: UUID
    org_id: UUID
    library_id: UUID
    scope_type: str
    drive_id: Optional[str] = None
    folder_id: Optional[str] = None
    folder_name: Optional[str] = None
    folder_path: Optional[str] = None
    change_token: Optional[str] = None
    last_sync_at: Optional[str] = None
    last_full_sync_at: Optional[str] = None
    lease_token: str = ""
    lease_expires_at: str = ""


@dataclass(frozen=True)
class UpsertResult:
    """Result of a batch file upsert operation."""

    created_count: int
    updated_count: int
    unchanged_count: int
    enqueued_jobs: dict[str, Any]
    metadata_updates: list[dict[str, str]]


@dataclass(frozen=True)
class DeleteResult:
    """Result of a batch file delete operation."""

    deleted_count: int
    not_found_count: int


@dataclass(frozen=True)
class MetadataUpdateResult:
    updated_scene_count: int
    skipped_count: int


@dataclass(frozen=True)
class AccessToken:
    """Short-lived Google access token returned by the token broker."""

    access_token: str
    token_type: str
    expires_at: str
    scope_type: str


@dataclass(frozen=True)
class ClaimedProcessingFile:
    """Represents a claimed file for processing (not enrichment)."""

    id: UUID
    org_id: UUID
    connection_id: UUID
    google_file_id: str
    file_name: str
    video_id: str
    mime_type: str
    md5_checksum: Optional[str] = None
    file_size_bytes: Optional[int] = None
    drive_path: Optional[str] = None
    web_view_link: Optional[str] = None
    library_id: Optional[UUID] = None
    scope_type: Optional[str] = None
    drive_id: Optional[str] = None
    lease_token: Optional[str] = None
    lease_expires_at: Optional[str] = None


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
                lease_token=f.get("lease_token"),
                lease_expires_at=f.get("lease_expires_at"),
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
        lease_token: Optional[str] = None,
    ) -> bool:
        """Update enrichment status for a file.
        Args:
            file_id: Drive file UUID.
            job_type: One of 'caption', 'stt', 'ocr', 'face'.
            status: One of 'done', 'failed'.
            error: Optional error description (max 2000 chars).
            lease_token: Lease token received from claim_jobs.
        Returns True on success.
        """
        url = f"{self.base_url.rstrip('/')}/internal/drive/jobs/{file_id}/status"
        payload: dict[str, Any] = {"job_type": job_type, "status": status}
        if error is not None:
            payload["error"] = error
        if lease_token is not None:
            payload["lease_token"] = lease_token
        data = self._request_with_retry("PATCH", url, json=payload)
        return data.get("ok", False)

    def get_file(self, file_id: UUID) -> dict[str, Any]:
        """Fetch file metadata for processing.

        Returns dict with id, org_id, video_id, keyframe_s3_prefix, and status fields.
        """
        url = f"{self.base_url.rstrip('/')}/internal/drive/files/{file_id}"
        return self._request_with_retry("GET", url)

    def claim_connection(self, limit: int = 1) -> list[ClaimedConnection]:
        """Claim active drive connections for sync."""
        url = f"{self.base_url.rstrip('/')}/internal/drive/sync/claim_connection"
        payload = {"limit": limit}
        data = self._request_with_retry("POST", url, json=payload)
        return [
            ClaimedConnection(
                connection_id=UUID(c["connection_id"]),
                org_id=UUID(c["org_id"]),
                library_id=UUID(c["library_id"]),
                scope_type=c["scope_type"],
                drive_id=c.get("drive_id"),
                folder_id=c.get("folder_id"),
                folder_name=c.get("folder_name"),
                folder_path=c.get("folder_path"),
                change_token=c.get("change_token"),
                last_sync_at=c.get("last_sync_at"),
                last_full_sync_at=c.get("last_full_sync_at"),
                lease_token=c.get("lease_token", ""),
                lease_expires_at=c.get("lease_expires_at", ""),
            )
            for c in data.get("connections", [])
        ]

    def upsert_files(
        self,
        connection_id: UUID,
        *,
        lease_token: str,
        items: list[dict[str, Any]],
    ) -> UpsertResult:
        """Batch upsert discovered files for a connection."""
        url = f"{self.base_url.rstrip('/')}/internal/drive/sync/connections/{connection_id}/upsert_files"
        payload = {"lease_token": lease_token, "items": items}
        data = self._request_with_retry("POST", url, json=payload)
        return UpsertResult(
            created_count=data["created_count"],
            updated_count=data["updated_count"],
            unchanged_count=data["unchanged_count"],
            enqueued_jobs=data.get("enqueued_jobs", {}),
            metadata_updates=data.get("metadata_updates", []),
        )

    def update_metadata(
        self,
        connection_id: UUID,
        *,
        lease_token: str,
        updates: list[dict[str, str]],
    ) -> MetadataUpdateResult:
        url = f"{self.base_url.rstrip('/')}/internal/drive/sync/connections/{connection_id}/update_metadata"
        payload = {"lease_token": lease_token, "updates": updates}
        data = self._request_with_retry("PATCH", url, json=payload)
        return MetadataUpdateResult(
            updated_scene_count=data.get("updated_scene_count", 0),
            skipped_count=data.get("skipped_count", 0),
        )

    def list_connection_file_ids(
        self,
        connection_id: UUID,
    ) -> set[str]:
        url = f"{self.base_url.rstrip('/')}/internal/drive/sync/connections/{connection_id}/file_ids"
        data = self._request_with_retry("GET", url)
        return set(data.get("google_file_ids", []))

    def checkpoint(
        self,
        connection_id: UUID,
        *,
        lease_token: str,
        change_token: Optional[str] = None,
        last_sync_at: Optional[str] = None,
        last_full_sync_at: Optional[str] = None,
        error_message: Optional[str] = None,
        drive_id: Optional[str] = None,
        release: bool = True,
    ) -> bool:
        """Update sync cursor and optionally release connection lease."""
        url = f"{self.base_url.rstrip('/')}/internal/drive/sync/connections/{connection_id}/checkpoint"
        payload: dict[str, Any] = {"lease_token": lease_token, "release": release}
        if change_token is not None:
            payload["change_token"] = change_token
        if last_sync_at is not None:
            payload["last_sync_at"] = last_sync_at
        if last_full_sync_at is not None:
            payload["last_full_sync_at"] = last_full_sync_at
        if error_message is not None:
            payload["error_message"] = error_message
        if drive_id is not None:
            payload["drive_id"] = drive_id
        data = self._request_with_retry("PATCH", url, json=payload)
        return data.get("ok", False)

    def delete_files(
        self,
        connection_id: UUID,
        *,
        lease_token: str,
        google_file_ids: list[str],
    ) -> DeleteResult:
        """Soft-delete files by their Google file IDs."""
        url = f"{self.base_url.rstrip('/')}/internal/drive/sync/connections/{connection_id}/delete_files"
        payload = {"lease_token": lease_token, "google_file_ids": google_file_ids}
        data = self._request_with_retry("POST", url, json=payload)
        return DeleteResult(
            deleted_count=data.get("deleted_count", 0),
            not_found_count=data.get("not_found_count", 0),
        )

    def get_drive_token(self, connection_id: UUID, *, lease_token: Optional[str] = None) -> AccessToken:
        """Get a short-lived Google access token for a connection.

        When ``lease_token`` is None the API skips connection-lease validation,
        which is the correct path for the processing worker (it holds a file
        lease, not a connection lease).
        """
        url = f"{self.base_url.rstrip('/')}/internal/drive/sync/connections/{connection_id}/token"
        payload: dict[str, Any] = {}
        if lease_token is not None:
            payload["lease_token"] = lease_token
        data = self._request_with_retry("POST", url, json=payload)
        return AccessToken(
            access_token=data["access_token"],
            token_type=data["token_type"],
            expires_at=data["expires_at"],
            scope_type=data["scope_type"],
        )

    def claim_processing(self, limit: int = 1) -> list[ClaimedProcessingFile]:
        """Claim pending files for video processing."""
        url = f"{self.base_url.rstrip('/')}/internal/drive/processing/claim"
        payload = {"limit": limit}
        data = self._request_with_retry("POST", url, json=payload)
        return [
            ClaimedProcessingFile(
                id=UUID(f["id"]),
                org_id=UUID(f["org_id"]),
                connection_id=UUID(f["connection_id"]),
                google_file_id=f["google_file_id"],
                file_name=f["file_name"],
                video_id=f["video_id"],
                mime_type=f["mime_type"],
                md5_checksum=f.get("md5_checksum"),
                file_size_bytes=f.get("file_size_bytes"),
                drive_path=f.get("drive_path"),
                web_view_link=f.get("web_view_link"),
                library_id=UUID(f["library_id"]) if f.get("library_id") else None,
                scope_type=f.get("scope_type"),
                drive_id=f.get("drive_id"),
                lease_token=f.get("lease_token"),
                lease_expires_at=f.get("lease_expires_at"),
            )
            for f in data.get("files", [])
        ]

    def update_processing_status(
        self,
        file_id: UUID,
        *,
        status: str,
        lease_token: Optional[str] = None,
        error: Optional[str] = None,
        original_s3_key: Optional[str] = None,
        original_size_bytes: Optional[int] = None,
        proxy_s3_key: Optional[str] = None,
        proxy_size_bytes: Optional[int] = None,
        proxy_duration_ms: Optional[int] = None,
        thumbnail_s3_prefix: Optional[str] = None,
        scene_count: Optional[int] = None,
        audio_s3_key: Optional[str] = None,
        keyframe_s3_prefix: Optional[str] = None,
    ) -> bool:
        """Update processing status for a file."""
        url = f"{self.base_url.rstrip('/')}/internal/drive/processing/{file_id}/status"
        payload: dict[str, Any] = {"status": status}
        if lease_token is not None:
            payload["lease_token"] = lease_token
        if error is not None:
            payload["error"] = error
        if original_s3_key is not None:
            payload["original_s3_key"] = original_s3_key
        if original_size_bytes is not None:
            payload["original_size_bytes"] = original_size_bytes
        if proxy_s3_key is not None:
            payload["proxy_s3_key"] = proxy_s3_key
        if proxy_size_bytes is not None:
            payload["proxy_size_bytes"] = proxy_size_bytes
        if proxy_duration_ms is not None:
            payload["proxy_duration_ms"] = proxy_duration_ms
        if thumbnail_s3_prefix is not None:
            payload["thumbnail_s3_prefix"] = thumbnail_s3_prefix
        if scene_count is not None:
            payload["scene_count"] = scene_count
        if audio_s3_key is not None:
            payload["audio_s3_key"] = audio_s3_key
        if keyframe_s3_prefix is not None:
            payload["keyframe_s3_prefix"] = keyframe_s3_prefix
        data = self._request_with_retry("PATCH", url, json=payload)
        return data.get("ok", False)

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
