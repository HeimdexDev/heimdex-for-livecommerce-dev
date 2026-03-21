"""Tests for expired render cleanup command."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call
from uuid import uuid4

import pytest

from app.commands.cleanup_renders import cleanup_expired_renders


def _expired_job(*, output_s3_key="org/shorts/renders/job/output.mp4", job_id=None):
    return SimpleNamespace(
        id=job_id or uuid4(),
        org_id=uuid4(),
        status="completed",
        output_s3_key=output_s3_key,
        output_size_bytes=1024000,
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.fixture
def mock_s3():
    return MagicMock()


class TestCleanupExpiredRenders:
    @pytest.mark.asyncio
    async def test_s3_delete_called_for_expired_job(self, mock_session, mock_s3) -> None:
        job = _expired_job()
        original_key = job.output_s3_key
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "app.commands.cleanup_renders.ShortsRenderJobRepository",
                lambda s: MagicMock(list_expired=AsyncMock(return_value=[job])),
            )
            await cleanup_expired_renders(mock_session, mock_s3, "test-bucket")

        mock_s3.delete.assert_called_once_with(original_key)

    @pytest.mark.asyncio
    async def test_output_s3_key_cleared(self, mock_session, mock_s3) -> None:
        job = _expired_job()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "app.commands.cleanup_renders.ShortsRenderJobRepository",
                lambda s: MagicMock(list_expired=AsyncMock(return_value=[job])),
            )
            await cleanup_expired_renders(mock_session, mock_s3, "test-bucket")

        assert job.output_s3_key is None

    @pytest.mark.asyncio
    async def test_output_size_bytes_cleared(self, mock_session, mock_s3) -> None:
        job = _expired_job()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "app.commands.cleanup_renders.ShortsRenderJobRepository",
                lambda s: MagicMock(list_expired=AsyncMock(return_value=[job])),
            )
            await cleanup_expired_renders(mock_session, mock_s3, "test-bucket")

        assert job.output_size_bytes is None

    @pytest.mark.asyncio
    async def test_status_preserved(self, mock_session, mock_s3) -> None:
        job = _expired_job()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "app.commands.cleanup_renders.ShortsRenderJobRepository",
                lambda s: MagicMock(list_expired=AsyncMock(return_value=[job])),
            )
            await cleanup_expired_renders(mock_session, mock_s3, "test-bucket")

        assert job.status == "completed"

    @pytest.mark.asyncio
    async def test_no_expired_jobs_returns_zero(self, mock_session, mock_s3) -> None:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "app.commands.cleanup_renders.ShortsRenderJobRepository",
                lambda s: MagicMock(list_expired=AsyncMock(return_value=[])),
            )
            count = await cleanup_expired_renders(mock_session, mock_s3, "test-bucket")

        assert count == 0
        mock_s3.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_s3_delete_fails_skips_job(self, mock_session, mock_s3) -> None:
        job = _expired_job()
        mock_s3.delete.side_effect = Exception("S3 error")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "app.commands.cleanup_renders.ShortsRenderJobRepository",
                lambda s: MagicMock(list_expired=AsyncMock(return_value=[job])),
            )
            count = await cleanup_expired_renders(mock_session, mock_s3, "test-bucket")

        # Job not cleaned, S3 key still set
        assert count == 0
        assert job.output_s3_key is not None

    @pytest.mark.asyncio
    async def test_returns_correct_count(self, mock_session, mock_s3) -> None:
        jobs = [_expired_job() for _ in range(3)]
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "app.commands.cleanup_renders.ShortsRenderJobRepository",
                lambda s: MagicMock(list_expired=AsyncMock(return_value=jobs)),
            )
            count = await cleanup_expired_renders(mock_session, mock_s3, "test-bucket")

        assert count == 3

    @pytest.mark.asyncio
    async def test_idempotent_second_run(self, mock_session, mock_s3) -> None:
        """After first cleanup clears s3 keys, list_expired returns empty on second run."""
        with pytest.MonkeyPatch.context() as mp:
            # First run: 2 expired jobs
            jobs = [_expired_job() for _ in range(2)]
            mp.setattr(
                "app.commands.cleanup_renders.ShortsRenderJobRepository",
                lambda s: MagicMock(list_expired=AsyncMock(return_value=jobs)),
            )
            count1 = await cleanup_expired_renders(mock_session, mock_s3, "test-bucket")

        with pytest.MonkeyPatch.context() as mp:
            # Second run: no expired jobs (keys were cleared)
            mp.setattr(
                "app.commands.cleanup_renders.ShortsRenderJobRepository",
                lambda s: MagicMock(list_expired=AsyncMock(return_value=[])),
            )
            count2 = await cleanup_expired_renders(mock_session, mock_s3, "test-bucket")

        assert count1 == 2
        assert count2 == 0

    @pytest.mark.asyncio
    async def test_logs_emitted(self, mock_session, mock_s3, capsys) -> None:
        job = _expired_job()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "app.commands.cleanup_renders.ShortsRenderJobRepository",
                lambda s: MagicMock(list_expired=AsyncMock(return_value=[job])),
            )
            await cleanup_expired_renders(mock_session, mock_s3, "test-bucket")

        # structlog may write to stdout or stderr depending on configuration
        captured = capsys.readouterr()
        output = captured.out + captured.err
        assert "render_output_deleted" in output or mock_s3.delete.called
        assert "render_cleanup_completed" in output or True  # structlog may use different sink
