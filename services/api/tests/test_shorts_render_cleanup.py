# pyright: reportUnknownParameterType=false, reportMissingParameterType=false, reportAny=false, reportUnusedCallResult=false, reportUnknownVariableType=false, reportUnknownMemberType=false
"""Tests for the shorts-render cleanup sweep.

Verifies the contract between list_expired / list_expired_without_output /
delete_one_by_id_internal and the module-level cleanup_expired_renders
orchestrator in service.py. Uses mock repo + mock S3 client — no database,
no boto3.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError

from app.modules.shorts_render.service import (
    CleanupResult,
    _is_safe_shorts_output_key,
    cleanup_expired_renders,
)


def _make_job(*, with_output: bool, status_: str = "completed", job_id=None, org_id=None):
    """Build a fake ShortsRenderJob just complete enough for cleanup.

    Uses a valid UUID for the org portion of the S3 key so the cleanup
    safety-belt pattern (`{uuid}/shorts/renders/{uuid}/output.mp4`)
    accepts it. Tests that want to exercise the safety belt assign
    ``job.output_s3_key`` directly to an unsafe value after construction.
    """
    job = MagicMock()
    job.id = job_id or uuid4()
    job.status = status_
    job_org = org_id or uuid4()
    job.output_s3_key = (
        f"{job_org}/shorts/renders/{job.id}/output.mp4" if with_output else None
    )
    job.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    return job


def _mock_repo(*, with_output=None, without_output=None):
    repo = MagicMock()
    repo.list_expired = AsyncMock(return_value=with_output or [])
    repo.list_expired_without_output = AsyncMock(return_value=without_output or [])
    repo.delete_one_by_id_internal = AsyncMock(return_value=True)
    return repo


def _mock_s3(*, raise_on_key=None, raise_error_code="InternalError"):
    s3 = MagicMock()

    def _delete(key):
        if raise_on_key and key == raise_on_key:
            raise ClientError(
                {"Error": {"Code": raise_error_code, "Message": "boom"}},
                "DeleteObject",
            )

    s3.delete = MagicMock(side_effect=_delete)
    return s3


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_empty_returns_zero_result():
    repo = _mock_repo()
    s3 = _mock_s3()

    result = await cleanup_expired_renders(repo, s3)

    assert isinstance(result, CleanupResult)
    assert result.total_expired == 0
    assert result.s3_deleted == 0
    assert result.db_deleted == 0
    s3.delete.assert_not_called()
    repo.delete_one_by_id_internal.assert_not_called()


@pytest.mark.asyncio
async def test_cleanup_deletes_s3_then_db_for_each_with_output_job():
    jobs = [_make_job(with_output=True) for _ in range(3)]
    repo = _mock_repo(with_output=jobs)
    s3 = _mock_s3()

    result = await cleanup_expired_renders(repo, s3)

    assert result.total_expired == 3
    assert result.s3_deleted == 3
    assert result.db_deleted == 3
    assert result.s3_failed == 0
    assert s3.delete.call_count == 3
    assert repo.delete_one_by_id_internal.call_count == 3


@pytest.mark.asyncio
async def test_cleanup_deletes_db_rows_for_failed_jobs_without_s3_call():
    """Failed jobs have no output_s3_key; cleanup must still drop the DB row."""
    failed_jobs = [
        _make_job(with_output=False, status_="failed"),
        _make_job(with_output=False, status_="failed"),
    ]
    repo = _mock_repo(without_output=failed_jobs)
    s3 = _mock_s3()

    result = await cleanup_expired_renders(repo, s3)

    assert result.total_expired == 2
    assert result.db_deleted == 2
    assert result.s3_deleted == 0
    s3.delete.assert_not_called()
    assert repo.delete_one_by_id_internal.call_count == 2


@pytest.mark.asyncio
async def test_cleanup_mixed_with_and_without_output():
    with_output = [_make_job(with_output=True) for _ in range(2)]
    without_output = [_make_job(with_output=False, status_="failed")]
    repo = _mock_repo(with_output=with_output, without_output=without_output)
    s3 = _mock_s3()

    result = await cleanup_expired_renders(repo, s3)

    assert result.total_expired == 3
    assert result.s3_deleted == 2
    assert result.db_deleted == 3


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_treats_nosuchkey_as_already_gone_and_still_deletes_db():
    jobs = [_make_job(with_output=True) for _ in range(3)]
    target_key = jobs[1].output_s3_key
    repo = _mock_repo(with_output=jobs)
    s3 = _mock_s3(raise_on_key=target_key, raise_error_code="NoSuchKey")

    result = await cleanup_expired_renders(repo, s3)

    assert result.s3_deleted == 2
    assert result.s3_skipped_not_found == 1
    assert result.s3_failed == 0
    # DB row for the "already gone" object still gets removed — idempotent
    assert result.db_deleted == 3


@pytest.mark.asyncio
async def test_cleanup_skips_db_delete_when_s3_delete_fails_unexpectedly():
    """Unknown S3 errors must NOT drop the DB row — we want a retry next pass."""
    jobs = [_make_job(with_output=True) for _ in range(3)]
    target_key = jobs[1].output_s3_key
    repo = _mock_repo(with_output=jobs)
    s3 = _mock_s3(raise_on_key=target_key, raise_error_code="InternalError")

    result = await cleanup_expired_renders(repo, s3)

    assert result.s3_deleted == 2
    assert result.s3_failed == 1
    # Only 2 DB deletes — the one with the failed S3 delete is skipped
    assert result.db_deleted == 2
    assert result.failed_keys[0][0] == target_key


@pytest.mark.asyncio
async def test_cleanup_failure_on_one_job_does_not_abort_remaining_jobs():
    """Per-job atomic: #2 failing must not block #3."""
    jobs = [_make_job(with_output=True) for _ in range(5)]
    target_key = jobs[1].output_s3_key
    repo = _mock_repo(with_output=jobs)
    s3 = _mock_s3(raise_on_key=target_key, raise_error_code="InternalError")

    result = await cleanup_expired_renders(repo, s3)

    assert result.s3_deleted == 4
    assert result.s3_failed == 1
    assert result.db_deleted == 4


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_dry_run_does_not_call_s3_or_db():
    with_output = [_make_job(with_output=True) for _ in range(3)]
    without_output = [_make_job(with_output=False, status_="failed") for _ in range(2)]
    repo = _mock_repo(with_output=with_output, without_output=without_output)
    s3 = _mock_s3()

    result = await cleanup_expired_renders(repo, s3, dry_run=True)

    assert result.dry_run is True
    assert result.total_expired == 5
    assert result.s3_deleted == 0
    assert result.db_deleted == 0
    s3.delete.assert_not_called()
    repo.delete_one_by_id_internal.assert_not_called()


@pytest.mark.asyncio
async def test_cleanup_uses_provided_now_for_deterministic_tests():
    """The ``now`` param flows through to the repository queries."""
    fixed_now = datetime(2026, 4, 13, 12, 0, 0, tzinfo=timezone.utc)
    repo = _mock_repo()
    s3 = _mock_s3()

    await cleanup_expired_renders(repo, s3, now=fixed_now)

    repo.list_expired.assert_awaited_once_with(fixed_now)
    repo.list_expired_without_output.assert_awaited_once_with(fixed_now)


# ---------------------------------------------------------------------------
# Safety belt: the pattern check refuses keys outside the shorts-render space
# ---------------------------------------------------------------------------


class TestSafeShortsOutputKeyPattern:
    """Unit-level coverage of the pattern validator. Exhaustive because it
    is the last line of defense against the bucket eating a video / scene
    thumbnail / drive proxy if some future bug writes one of those paths
    into ``ShortsRenderJob.output_s3_key``."""

    def test_accepts_canonical_worker_output(self):
        key = (
            "11111111-1111-1111-1111-111111111111"
            "/shorts/renders/"
            "22222222-2222-2222-2222-222222222222/output.mp4"
        )
        assert _is_safe_shorts_output_key(key) is True

    def test_accepts_uppercase_hex(self):
        key = (
            "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"
            "/shorts/renders/"
            "FFFFFFFF-1111-2222-3333-444444444444/output.mp4"
        )
        assert _is_safe_shorts_output_key(key) is True

    def test_rejects_scene_thumbnail_path(self):
        key = "11111111-1111-1111-1111-111111111111/scenes/abc123/thumb.jpg"
        assert _is_safe_shorts_output_key(key) is False

    def test_rejects_drive_proxy_path(self):
        key = "drive/proxies/gd_xyz/video.mp4"
        assert _is_safe_shorts_output_key(key) is False

    def test_rejects_missing_shorts_prefix(self):
        key = (
            "11111111-1111-1111-1111-111111111111"
            "/renders/"
            "22222222-2222-2222-2222-222222222222/output.mp4"
        )
        assert _is_safe_shorts_output_key(key) is False

    def test_rejects_non_uuid_org_prefix(self):
        key = "my-org/shorts/renders/22222222-2222-2222-2222-222222222222/output.mp4"
        assert _is_safe_shorts_output_key(key) is False

    def test_rejects_path_traversal_attempt(self):
        key = (
            "11111111-1111-1111-1111-111111111111"
            "/shorts/renders/"
            "22222222-2222-2222-2222-222222222222/../../../etc/passwd"
        )
        assert _is_safe_shorts_output_key(key) is False

    def test_rejects_non_mp4_extension(self):
        key = (
            "11111111-1111-1111-1111-111111111111"
            "/shorts/renders/"
            "22222222-2222-2222-2222-222222222222/output.mov"
        )
        assert _is_safe_shorts_output_key(key) is False


@pytest.mark.asyncio
async def test_cleanup_refuses_to_delete_unsafe_keys_and_keeps_db_row():
    """A job with an output_s3_key outside the shorts-render namespace
    must trip the safety belt — cleanup skips S3 entirely, DOES NOT drop
    the DB row, and surfaces the key for human review."""
    safe_job = _make_job(with_output=True)
    # Simulate a future bug: a thumbnail path snuck into output_s3_key
    unsafe_job = _make_job(with_output=True)
    unsafe_job.output_s3_key = "org123/scenes/thumb.jpg"
    repo = _mock_repo(with_output=[safe_job, unsafe_job])
    s3 = _mock_s3()

    result = await cleanup_expired_renders(repo, s3)

    # Safe job was processed normally
    assert result.s3_deleted == 1
    # Unsafe job was skipped: no S3 call, no DB delete
    assert result.s3_skipped_unsafe_key == 1
    assert result.unsafe_keys == ["org123/scenes/thumb.jpg"]
    assert result.db_deleted == 1  # only the safe one
    # Verify s3.delete was NOT called with the unsafe key
    called_keys = [call.args[0] for call in s3.delete.call_args_list]
    assert "org123/scenes/thumb.jpg" not in called_keys


@pytest.mark.asyncio
async def test_cleanup_dry_run_also_refuses_unsafe_keys():
    """Dry-run logging must not print 'would delete' for unsafe keys —
    the safety check runs BEFORE the dry-run branch."""
    unsafe_job = _make_job(with_output=True)
    unsafe_job.output_s3_key = "drive/proxies/video.mp4"
    repo = _mock_repo(with_output=[unsafe_job])
    s3 = _mock_s3()

    result = await cleanup_expired_renders(repo, s3, dry_run=True)

    assert result.s3_skipped_unsafe_key == 1
    assert result.unsafe_keys == ["drive/proxies/video.mp4"]
    assert result.db_deleted == 0
    s3.delete.assert_not_called()
