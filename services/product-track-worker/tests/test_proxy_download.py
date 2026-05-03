"""Unit tests for ``src.proxy_download``. No real S3 in the loop —
the helper is structural-typed against an ``S3DownloadClient``
Protocol, so a stub class is enough."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.proxy_download import downloaded_proxy


class _StubS3:
    """Records calls + simulates a successful download by writing
    placeholder bytes at the requested local path. Tests assert
    against ``calls`` and against the file existing during the
    ``with`` block."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Path]] = []

    def download_file(self, s3_key: str, local_path: Path) -> None:
        self.calls.append((s3_key, local_path))
        # Simulate the real boto3 download by creating a file at the
        # target. Tests use this to verify the path is reachable
        # inside the ``with`` and gone after.
        local_path.write_bytes(b"fake-mp4-bytes")


def test_downloads_to_tempdir_named_by_job_id(tmp_path):
    s3 = _StubS3()
    with downloaded_proxy(
        s3=s3,
        proxy_s3_key="org/drive/d/g/proxy.mp4",
        job_id_for_naming="job-abc",
        parent_dir=tmp_path,
    ) as local:
        # Path lives under tmp_path (not /tmp) and the dirname
        # carries the job id so concurrent jobs can't collide.
        assert tmp_path in local.parents
        assert "job-abc" in local.parent.name
        assert local.name == "proxy.mp4"
        assert local.exists()

    # Tempdir cleaned up on normal exit.
    assert not local.exists()
    # Exactly one S3 GET issued (key contract — the worker calls
    # this once per message, not once per scene).
    assert s3.calls == [("org/drive/d/g/proxy.mp4", local)]


def test_cleans_up_on_exception_inside_with_block(tmp_path):
    """The ``with`` cleanup MUST run even when the body raises (F4
    stage-wide-failure path). Aircloud /tmp is tight; a leak across
    retries would wedge the container."""
    s3 = _StubS3()
    captured_path: Path | None = None
    with pytest.raises(RuntimeError, match="boom"):
        with downloaded_proxy(
            s3=s3,
            proxy_s3_key="k",
            job_id_for_naming="job-xyz",
            parent_dir=tmp_path,
        ) as local:
            captured_path = local
            assert captured_path.exists()
            raise RuntimeError("boom")

    assert captured_path is not None
    assert not captured_path.exists()
    assert not captured_path.parent.exists(), "tempdir must be removed on exception"


def test_raises_value_error_on_empty_key(tmp_path):
    """Defensive: callers should null-check before calling, but if
    they don't, fail loudly rather than letting boto3 emit a
    cryptic ``InvalidArgument`` that buries the root cause."""
    s3 = _StubS3()
    with pytest.raises(ValueError, match="proxy_s3_key is empty"):
        with downloaded_proxy(
            s3=s3,
            proxy_s3_key="",
            job_id_for_naming="job-xyz",
            parent_dir=tmp_path,
        ):
            pass
    # No S3 call attempted on the empty-key path.
    assert s3.calls == []


def test_propagates_s3_download_failure(tmp_path):
    """Real S3 errors propagate so the worker's outer try/except
    can map them to ``error_code=proxy_download_failed`` rather than
    swallowing — the worker would silently bill the user otherwise."""
    s3 = MagicMock()
    s3.download_file.side_effect = RuntimeError("S3 timeout")
    with pytest.raises(RuntimeError, match="S3 timeout"):
        with downloaded_proxy(
            s3=s3,
            proxy_s3_key="k",
            job_id_for_naming="job",
            parent_dir=tmp_path,
        ):
            pass
