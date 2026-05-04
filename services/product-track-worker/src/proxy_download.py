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

2026-05-04 Aircloud /tmp incident:
  Real livecommerce proxies on devorg run ~500 MB (64-min H.264 at
  ~900 kbit/s). The default Python ``tempfile.TemporaryDirectory``
  uses ``/tmp`` which on Aircloud is a small tmpfs; downloads
  silently truncate (or boto3's TransferManager fails partway) and
  cv2 then can't open the proxy → every per-scene SAM2 call raises
  → looks like a SAM2 OOM but is really a disk-pressure issue.

  Fix: default to ``/var/tmp`` (real disk on Aircloud, plenty of
  space). Plus a post-download integrity check that compares the
  local file size against the S3 ``ContentLength`` so a partial
  download fails LOUDLY with a distinct error instead of silently
  poisoning every SAM2 call downstream.
"""

from __future__ import annotations

import logging
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional, Protocol

logger = logging.getLogger(__name__)


# Default scratch dir. ``/var/tmp`` is on real disk on Aircloud
# (whereas ``/tmp`` is tmpfs); fall back gracefully on hosts that
# don't have it (some minimal containers) by setting to ``None``
# which lets ``tempfile`` pick the system default.
_DEFAULT_PROXY_SCRATCH_DIR: Optional[Path] = (
    Path("/var/tmp") if Path("/var/tmp").is_dir() else None
)


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
    expected_size_bytes: int | None = None,
) -> Iterator[Path]:
    """Download ``proxy_s3_key`` to a per-job tempdir, yield the
    local path, and clean up on exit (success OR exception).

    ``job_id_for_naming`` is incorporated into the tempdir name so
    concurrent jobs in the same worker process never collide on
    disk — even when ``DRIVE_PRODUCT_TRACK_CONCURRENCY`` is ever
    bumped above 1. The handoff calls out concurrency=1 today, but
    naming this way costs nothing and removes a future foot-gun.

    ``parent_dir`` defaults to ``/var/tmp`` on hosts where it
    exists (Aircloud, most Linux servers) so we don't fight tmpfs
    pressure on ``/tmp``. Tests inject a pytest ``tmp_path``.

    ``expected_size_bytes``, if provided, is compared against the
    downloaded file's size; mismatch raises ``RuntimeError`` with
    a distinct ``proxy_download_truncated`` signature so the
    failure mode shows up in worker logs rather than silently
    poisoning every downstream SAM2 call. Callers typically pass
    the S3 ``ContentLength`` from a ``head_object`` call. ``None``
    skips the size match (still verifies the file is non-empty).
    """
    if not proxy_s3_key:
        # Defensive — callers should have null-checked already, but
        # raise loudly here rather than letting boto3 produce a
        # cryptic ``InvalidArgument`` that buries the root cause.
        raise ValueError("proxy_s3_key is empty; cannot download")

    effective_parent = (
        parent_dir if parent_dir is not None else _DEFAULT_PROXY_SCRATCH_DIR
    )
    with tempfile.TemporaryDirectory(
        prefix=f"track_{job_id_for_naming}_",
        dir=str(effective_parent) if effective_parent is not None else None,
    ) as td:
        local_path = Path(td) / "proxy.mp4"
        logger.info(
            "proxy_download_start",
            extra={
                "proxy_s3_key": proxy_s3_key,
                "local_path": str(local_path),
                "job_id": job_id_for_naming,
                "expected_size_bytes": expected_size_bytes,
            },
        )
        s3.download_file(proxy_s3_key, local_path)
        local_size = local_path.stat().st_size if local_path.exists() else 0

        # Integrity gate: catch tmpfs-truncation / partial download.
        # 0 bytes is always wrong — boto3's ``download_file`` is
        # supposed to either complete or raise, but in practice on
        # Aircloud's tmpfs we've seen silent partial writes.
        if local_size == 0:
            raise RuntimeError(
                f"proxy_download_zero_bytes: download produced an "
                f"empty file at {local_path} (key={proxy_s3_key}, "
                f"job_id={job_id_for_naming}). Likely "
                f"out-of-disk-space on the worker's scratch dir."
            )
        if expected_size_bytes is not None and local_size != expected_size_bytes:
            raise RuntimeError(
                f"proxy_download_truncated: local size {local_size} != "
                f"expected {expected_size_bytes} (key={proxy_s3_key}, "
                f"job_id={job_id_for_naming}). Likely "
                f"out-of-disk-space on the worker's scratch dir, or "
                f"S3 object mutated mid-download."
            )

        logger.info(
            "proxy_download_done",
            extra={
                "proxy_s3_key": proxy_s3_key,
                "size_bytes": local_size,
                "expected_size_bytes": expected_size_bytes,
                "job_id": job_id_for_naming,
            },
        )
        yield local_path
        # Tempdir auto-cleans on context exit (success path).

    # On exception, the ``with`` above still runs cleanup before
    # re-raising — verified in test_proxy_download.py.
