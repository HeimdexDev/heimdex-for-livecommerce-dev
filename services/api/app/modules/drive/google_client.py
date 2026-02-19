import hashlib
import logging
import time
from pathlib import Path
from typing import Any, Optional

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account
from googleapiclient.discovery import build

from app.config import get_settings

logger = logging.getLogger(__name__)

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
DRIVE_API_VERSION = "v3"
VIDEO_MIME_PREFIXES = ("video/",)

RETRYABLE_STATUS_CODES = {429, 500, 502, 503}
MAX_RETRIES = 3
INITIAL_BACKOFF = 2.0


class DriveClient:
    def __init__(self, sa_key_info: dict[str, Any], impersonate_email: str):
        self._credentials = service_account.Credentials.from_service_account_info(
            sa_key_info,
            scopes=DRIVE_SCOPES,
            subject=impersonate_email,
        )
        self._service = build("drive", DRIVE_API_VERSION, credentials=self._credentials)

    def _ensure_valid_credentials(self) -> None:
        if not self._credentials.valid:
            self._credentials.refresh(GoogleAuthRequest())

    def list_drive_files(
        self,
        drive_id: str,
        page_token: Optional[str] = None,
        page_size: int = 100,
    ) -> dict[str, Any]:
        self._ensure_valid_credentials()
        query = "mimeType contains 'video/' and trashed = false"
        return (
            self._service.files()
            .list(
                corpora="drive",
                driveId=drive_id,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                q=query,
                fields="nextPageToken,files(id,name,mimeType,size,md5Checksum,modifiedTime,createdTime,parents)",
                pageSize=page_size,
                pageToken=page_token,
            )
            .execute()
        )

    def get_changes(
        self,
        drive_id: str,
        page_token: str,
    ) -> dict[str, Any]:
        self._ensure_valid_credentials()
        return (
            self._service.changes()
            .list(
                pageToken=page_token,
                driveId=drive_id,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                fields="nextPageToken,newStartPageToken,changes(fileId,removed,file(id,name,mimeType,size,md5Checksum,modifiedTime,trashed,parents))",
                spaces="drive",
            )
            .execute()
        )

    def get_start_page_token(self, drive_id: str) -> str:
        self._ensure_valid_credentials()
        result = (
            self._service.changes()
            .getStartPageToken(
                driveId=drive_id,
                supportsAllDrives=True,
            )
            .execute()
        )
        return result["startPageToken"]

    def download_file_with_resume(
        self,
        file_id: str,
        dest_path: Path,
        expected_md5: Optional[str] = None,
        chunk_size: Optional[int] = None,
    ) -> Path:
        """Download a file from Drive using Range headers for resumability."""
        self._ensure_valid_credentials()
        settings = get_settings()
        chunk = chunk_size or settings.drive_download_chunk_size

        import requests as http_requests

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        downloaded = dest_path.stat().st_size if dest_path.exists() else 0

        url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&supportsAllDrives=true"
        headers = {"Authorization": f"Bearer {self._credentials.token}"}

        while True:
            range_header = f"bytes={downloaded}-"
            headers["Range"] = range_header

            response = self._execute_with_retry(
                lambda: http_requests.get(url, headers=headers, stream=True, timeout=300)
            )

            if response.status_code == 416:
                break
            response.raise_for_status()

            with open(dest_path, "ab") as f:
                for data_chunk in response.iter_content(chunk_size=chunk):
                    f.write(data_chunk)
                    downloaded += len(data_chunk)

            content_range = response.headers.get("Content-Range", "")
            if "/" in content_range:
                total = int(content_range.split("/")[-1])
                if downloaded >= total:
                    break
            else:
                break

        if expected_md5:
            actual_md5 = hashlib.md5(dest_path.read_bytes()).hexdigest()
            if actual_md5 != expected_md5:
                raise ValueError(f"MD5 mismatch: expected {expected_md5}, got {actual_md5}")

        logger.info(
            "drive_download_complete",
            extra={"file_id": file_id, "size_bytes": downloaded, "path": str(dest_path)},
        )
        return dest_path

    def get_file_path(self, file_id: str, drive_id: str) -> str:
        self._ensure_valid_credentials()
        parts: list[str] = []
        current_id = file_id

        for _ in range(20):
            meta = (
                self._service.files()
                .get(fileId=current_id, supportsAllDrives=True, fields="name,parents")
                .execute()
            )
            parts.append(meta["name"])
            parents = meta.get("parents", [])
            if not parents or parents[0] == drive_id:
                break
            current_id = parents[0]

        parts.reverse()
        return "/".join(parts)

    @staticmethod
    def _execute_with_retry(request_fn, max_retries: int = MAX_RETRIES) -> Any:
        backoff = INITIAL_BACKOFF
        for attempt in range(max_retries + 1):
            response = request_fn()
            if response.status_code not in RETRYABLE_STATUS_CODES:
                return response
            if attempt < max_retries:
                logger.warning(
                    "drive_api_retry",
                    extra={"status": response.status_code, "attempt": attempt + 1, "backoff": backoff},
                )
                time.sleep(backoff)
                backoff *= 2
        return response
