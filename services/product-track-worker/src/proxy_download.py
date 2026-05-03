"""Per-job proxy download + tempdir lifecycle.

Phase 3c-B locked decision (handoff sam2-proxy-handoff-2026-05-04):
the SAM2 wrapper consumes a SINGLE full-video proxy and slices each
candidate scene's window in-memory, instead of expecting per-scene
mp4s that no production pipeline writes. This module owns the
download + cleanup so ``tasks/track.py`` stays small and the
S3-side concerns are testable in isolation.

Loose-coupling rules enforced here:
  * Lib (heimdex_media_pipelines) is NOT imported — pipelines is
    pure data flow and never sees this path; the worker passes the
    local path through as opaque data.
  * The downloader takes a structural ``S3DownloadClient`` protocol,
    not a concrete ``S3Client``, so unit tests can pass a stub
    without touching boto3.
  * Tempdir lifetime is tied to a context manager so the F4 path
    (every SAM2 call raises) and the happy path both clean up
    deterministically. Aircloud /tmp is small (~tmpfs); leaking
    even a few hundred MB across job retries would wedge the
    container.
"""

from __future__ import annotations

import logging
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Protocol

logger = logging.getLogger(__name__)


class S3DownloadClient(Protocol):
    """Structural type for the subset of ``heimdex_worker_sdk.s3.S3Client``
    we use here. Keeping this narrow lets test stubs implement just
    ``download_file`` without faking the full S3Client surface."""

    def download_file(self, s3_key: str, local_path: Path) -> None: ...


@contextmanager
def downloaded_proxy(
    *,
    s3: S3DownloadClient,
    proxy_s3_key: str,
    job_id_for_naming: str,
    parent_dir: Path | None = None,
) -> Iterator[Path]:
    """Download ``proxy_s3_key`` to a per-job tempdir, yield the
    local path, and clean up on exit (success OR exception).

    ``job_id_for_naming`` is incorporated into the tempdir name so
    concurrent jobs in the same worker process never collide on
    disk — even when ``DRIVE_PRODUCT_TRACK_CONCURRENCY`` is ever
    bumped above 1. The handoff calls out concurrency=1 today, but
    naming this way costs nothing and removes a future foot-gun.

    ``parent_dir`` defaults to the system temp dir; tests inject a
    pytest ``tmp_path`` so they don't pollute /tmp.
    """
    if not proxy_s3_key:
        # Defensive — callers should have null-checked already, but
        # raise loudly here rather than letting boto3 produce a
        # cryptic ``InvalidArgument`` that buries the root cause.
        raise ValueError("proxy_s3_key is empty; cannot download")

    with tempfile.TemporaryDirectory(
        prefix=f"track_{job_id_for_naming}_",
        dir=str(parent_dir) if parent_dir is not None else None,
    ) as td:
        local_path = Path(td) / "proxy.mp4"
        logger.info(
            "proxy_download_start",
            extra={
                "proxy_s3_key": proxy_s3_key,
                "local_path": str(local_path),
                "job_id": job_id_for_naming,
            },
        )
        s3.download_file(proxy_s3_key, local_path)
        logger.info(
            "proxy_download_done",
            extra={
                "proxy_s3_key": proxy_s3_key,
                "size_bytes": (
                    local_path.stat().st_size if local_path.exists() else None
                ),
                "job_id": job_id_for_naming,
            },
        )
        yield local_path
        # Tempdir auto-cleans on context exit (success path).

    # On exception, the ``with`` above still runs cleanup before
    # re-raising — verified in test_proxy_download.py.
