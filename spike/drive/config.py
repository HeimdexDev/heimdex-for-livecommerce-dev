"""Centralized configuration for Drive spike experiments.

All config comes from environment variables with SPIKE_ prefix.
No defaults for credentials — scripts must fail loudly if not set.
"""

import os
import sys
from pathlib import Path


# --- Required credentials (no defaults — must be set) ---

SA_KEY_PATH: str = os.environ.get("SPIKE_SA_KEY_PATH", "")
DRIVE_ID: str = os.environ.get("SPIKE_DRIVE_ID", "")
IMPERSONATE_EMAIL: str = os.environ.get("SPIKE_IMPERSONATE_EMAIL", "")

# --- Optional tuning ---

# Download chunk size (default 10 MB)
DOWNLOAD_CHUNK_SIZE: int = int(os.environ.get("SPIKE_DOWNLOAD_CHUNK_MB", "10")) * 1024 * 1024

# Temp directory for downloads (default: spike/drive/tmp/)
TEMP_DIR: Path = Path(os.environ.get("SPIKE_TEMP_DIR", str(Path(__file__).parent / "tmp")))

# Log directory
LOG_DIR: Path = Path(__file__).parent / "logs"

# DWD scopes — read-only is all we need for spike
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# Drive API video MIME types we care about
VIDEO_MIME_TYPES = [
    "video/mp4",
    "video/quicktime",
    "video/x-msvideo",
    "video/x-matroska",
    "video/webm",
    "video/mpeg",
    "video/3gpp",
    "video/x-flv",
    "video/x-ms-wmv",
]

# File fields to request from Drive API
FILE_FIELDS = "id, name, mimeType, size, md5Checksum, modifiedTime, createdTime, parents, trashed"
FILE_LIST_FIELDS = f"nextPageToken, files({FILE_FIELDS})"


def validate() -> None:
    """Validate that all required config is present. Exit with clear message if not."""
    errors: list[str] = []

    if not SA_KEY_PATH:
        errors.append("SPIKE_SA_KEY_PATH not set (path to service account JSON key)")
    elif not Path(SA_KEY_PATH).is_file():
        errors.append(f"SPIKE_SA_KEY_PATH file not found: {SA_KEY_PATH}")

    if not DRIVE_ID:
        errors.append("SPIKE_DRIVE_ID not set (Shared Drive ID, e.g. 0AF...)")

    if not IMPERSONATE_EMAIL:
        errors.append("SPIKE_IMPERSONATE_EMAIL not set (Workspace user email for DWD)")

    if errors:
        print("=" * 60, file=sys.stderr)
        print("SPIKE CONFIGURATION ERROR", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        for e in errors:
            print(f"  ✗ {e}", file=sys.stderr)
        print("", file=sys.stderr)
        print("Set these environment variables before running:", file=sys.stderr)
        print("  export SPIKE_SA_KEY_PATH=/path/to/sa-key.json", file=sys.stderr)
        print("  export SPIKE_DRIVE_ID=0AF...", file=sys.stderr)
        print("  export SPIKE_IMPERSONATE_EMAIL=admin@yourdomain.com", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        sys.exit(1)


def ensure_dirs() -> None:
    """Create temp and log directories if they don't exist."""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def get_drive_service():
    """Build an authenticated Drive API v3 service using DWD.

    Returns (service, auth_time_ms) tuple.
    """
    import time
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    t0 = time.monotonic()
    credentials = service_account.Credentials.from_service_account_file(
        SA_KEY_PATH,
        scopes=SCOPES,
        subject=IMPERSONATE_EMAIL,
    )
    service = build("drive", "v3", credentials=credentials)
    auth_time_ms = (time.monotonic() - t0) * 1000

    return service, credentials, auth_time_ms


def get_authorized_session():
    """Build an AuthorizedSession for manual HTTP requests (Range header downloads).

    Returns (session, credentials, auth_time_ms) tuple.
    """
    import time
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession

    t0 = time.monotonic()
    credentials = service_account.Credentials.from_service_account_file(
        SA_KEY_PATH,
        scopes=SCOPES,
        subject=IMPERSONATE_EMAIL,
    )
    session = AuthorizedSession(credentials)
    auth_time_ms = (time.monotonic() - t0) * 1000

    return session, credentials, auth_time_ms
