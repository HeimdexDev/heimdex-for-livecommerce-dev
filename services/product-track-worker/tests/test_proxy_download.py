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


# ---------- integrity gate (PR D) ----------


def test_zero_byte_download_raises_proxy_download_zero_bytes(tmp_path):
    """Defensive against silent /tmp truncation. boto3's
    ``download_file`` is supposed to either complete or raise, but
    on Aircloud's tmpfs we observed silent partial writes. A
    0-byte file is always a fault — surface it loudly so the
    operator sees ``proxy_download_zero_bytes`` instead of every
    downstream cv2 call failing as if SAM2 itself crashed."""

    class _ZeroByteS3:
        def download_file(self, s3_key: str, local_path):
            local_path.touch()  # 0 bytes

    with pytest.raises(RuntimeError, match="proxy_download_zero_bytes"):
        with downloaded_proxy(
            s3=_ZeroByteS3(),
            proxy_s3_key="k",
            job_id_for_naming="job",
            parent_dir=tmp_path,
        ):
            pass


def test_size_mismatch_raises_proxy_download_truncated(tmp_path):
    """When the caller knows the expected size (head_object), the
    integrity check enforces a strict match. This catches partial
    downloads that ``download_file`` somehow returned without
    raising, and surfaces them with a distinct
    ``proxy_download_truncated`` signature so the failure mode
    isn't confused with SAM2 OOM."""

    class _PartialS3:
        def download_file(self, s3_key, local_path):
            # Wrote 100 bytes but caller expected 1000.
            local_path.write_bytes(b"x" * 100)

    with pytest.raises(RuntimeError, match="proxy_download_truncated"):
        with downloaded_proxy(
            s3=_PartialS3(),
            proxy_s3_key="k",
            job_id_for_naming="job",
            parent_dir=tmp_path,
            expected_size_bytes=1000,
        ):
            pass


def test_expected_size_match_passes(tmp_path):
    """Happy path: bytes downloaded match expected size → yield
    proceeds normally."""

    class _GoodS3:
        def download_file(self, s3_key, local_path):
            local_path.write_bytes(b"x" * 12345)

    with downloaded_proxy(
        s3=_GoodS3(),
        proxy_s3_key="k",
        job_id_for_naming="job",
        parent_dir=tmp_path,
        expected_size_bytes=12345,
    ) as local:
        assert local.stat().st_size == 12345


def test_expected_size_none_skips_match_but_still_checks_nonzero(tmp_path):
    """Best-effort case: when ``head_object`` failed, the caller
    passes ``None`` and we still gate on size > 0 — a 0-byte
    download is a fault regardless of whether the caller could
    learn the expected size."""

    class _ZeroByteS3:
        def download_file(self, s3_key, local_path):
            local_path.touch()

    with pytest.raises(RuntimeError, match="proxy_download_zero_bytes"):
        with downloaded_proxy(
            s3=_ZeroByteS3(),
            proxy_s3_key="k",
            job_id_for_naming="job",
            parent_dir=tmp_path,
            expected_size_bytes=None,
        ):
            pass


def test_default_parent_dir_uses_var_tmp_when_available(monkeypatch, tmp_path):
    """Locks the contract that the default scratch dir is
    ``/var/tmp`` (real disk on Aircloud), not the system default
    ``/tmp`` (tmpfs on Aircloud). The 2026-05-04 incident showed
    every per-scene SAM2 call failing after a 503 MB proxy
    silently truncated on tmpfs — switching the default removes
    that whole class of failure on Aircloud while staying
    compatible with hosts that don't have ``/var/tmp``."""
    from src import proxy_download as pd

    # Verify the module-level default points at /var/tmp on this
    # machine. Skip the assertion gracefully on hosts that don't
    # have /var/tmp (very minimal containers) — the fallback to
    # ``None`` (system default) is documented behavior.
    if Path("/var/tmp").is_dir():
        assert pd._DEFAULT_PROXY_SCRATCH_DIR == Path("/var/tmp")
    else:
        assert pd._DEFAULT_PROXY_SCRATCH_DIR is None

    # And the runtime path: when no ``parent_dir`` is passed, the
    # module honours the default. Patch the default to ``tmp_path``
    # so the test doesn't actually pollute /var/tmp.
    monkeypatch.setattr(pd, "_DEFAULT_PROXY_SCRATCH_DIR", tmp_path)

    class _StubS3:
        def download_file(self, s3_key, local_path):
            local_path.write_bytes(b"x" * 100)

    with downloaded_proxy(
        s3=_StubS3(),
        proxy_s3_key="k",
        job_id_for_naming="default-dir-test",
        # parent_dir intentionally omitted to exercise the default.
    ) as local:
        # The download landed under tmp_path (the patched default).
        assert tmp_path in local.parents
