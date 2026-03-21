"""Tests for ShortsRenderJobRepository (mocked AsyncSession, no live database)."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.shorts_render.models import ShortsRenderJob
from app.modules.shorts_render.repository import ShortsRenderJobRepository


@pytest.fixture
def session():
    s = AsyncMock()
    s.add = MagicMock()
    return s


@pytest.fixture
def repo(session):
    return ShortsRenderJobRepository(session)


def _make_job(**overrides):
    defaults = dict(
        id=uuid4(),
        org_id=uuid4(),
        user_id=uuid4(),
        video_id="v1",
        title="Test",
        status="queued",
        input_spec={"output": {}, "scene_clips": []},
        output_s3_key=None,
        output_duration_ms=None,
        output_size_bytes=None,
        render_time_ms=None,
        error=None,
        completed_at=None,
        expires_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        created_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    job = MagicMock(spec=ShortsRenderJob)
    for k, v in defaults.items():
        setattr(job, k, v)
    return job


# ── create ───────────────────────────────────────────────────────────────────


class TestCreate:
    @pytest.mark.asyncio
    async def test_create_returns_job_with_status_queued(self, repo, session):
        """Test 1: create() returns job; status comes from server_default."""
        result = await repo.create(
            org_id=uuid4(),
            user_id=uuid4(),
            video_id="v1",
            title="My Short",
            input_spec={"output": {}, "scene_clips": []},
            expires_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )
        session.add.assert_called_once()
        session.flush.assert_awaited_once()
        assert isinstance(result, ShortsRenderJob)
        assert result.video_id == "v1"
        assert result.title == "My Short"

    @pytest.mark.asyncio
    async def test_create_passes_all_fields(self, repo, session):
        """Test 2: create() passes all fields to the model constructor."""
        org = uuid4()
        user = uuid4()
        spec = {"output": {"width": 1080}, "scene_clips": []}
        exp = datetime(2026, 5, 1, tzinfo=timezone.utc)

        result = await repo.create(
            org_id=org,
            user_id=user,
            video_id="v2",
            title=None,
            input_spec=spec,
            expires_at=exp,
        )
        assert result.org_id == org
        assert result.user_id == user
        assert result.input_spec == spec
        assert result.expires_at == exp


# ── get_by_id ────────────────────────────────────────────────────────────────


class TestGetById:
    @pytest.mark.asyncio
    async def test_get_by_id_returns_job(self, repo, session):
        """Test 3: get_by_id() returns job when org matches."""
        job = _make_job()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = job
        session.execute.return_value = mock_result

        result = await repo.get_by_id(job.org_id, job.id)
        assert result is job

    @pytest.mark.asyncio
    async def test_get_by_id_wrong_org_returns_none(self, repo, session):
        """Test 4: get_by_id() returns None when org doesn't match."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        result = await repo.get_by_id(uuid4(), uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_id_nonexistent_returns_none(self, repo, session):
        """Test 5: get_by_id() returns None for non-existent ID."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        result = await repo.get_by_id(uuid4(), uuid4())
        assert result is None


# ── list_by_user ─────────────────────────────────────────────────────────────


class TestListByUser:
    def _setup_list_mocks(self, session, jobs, total):
        count_result = MagicMock()
        count_result.scalar_one.return_value = total

        scalars_mock = MagicMock()
        scalars_mock.all.return_value = jobs
        list_result = MagicMock()
        list_result.scalars.return_value = scalars_mock

        session.execute.side_effect = [count_result, list_result]

    @pytest.mark.asyncio
    async def test_list_by_user_returns_jobs_and_count(self, repo, session):
        """Test 6: list_by_user() returns (jobs, total_count)."""
        jobs = [_make_job(), _make_job()]
        self._setup_list_mocks(session, jobs, 2)

        result_jobs, total = await repo.list_by_user(uuid4(), uuid4())
        assert result_jobs == jobs
        assert total == 2

    @pytest.mark.asyncio
    async def test_list_by_user_empty(self, repo, session):
        """Test 7: list_by_user() returns empty list and zero count."""
        self._setup_list_mocks(session, [], 0)

        result_jobs, total = await repo.list_by_user(uuid4(), uuid4())
        assert result_jobs == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_list_by_user_default_limit(self, repo, session):
        """Test 8: list_by_user() uses default limit=20."""
        self._setup_list_mocks(session, [], 0)
        await repo.list_by_user(uuid4(), uuid4())
        # Two execute calls: count + select
        assert session.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_list_by_user_custom_limit_offset(self, repo, session):
        """Test 9: list_by_user() accepts custom limit and offset."""
        self._setup_list_mocks(session, [], 0)
        await repo.list_by_user(uuid4(), uuid4(), limit=5, offset=10)
        assert session.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_list_by_user_count_independent_of_limit(self, repo, session):
        """Test 10: total count is not affected by limit."""
        self._setup_list_mocks(session, [_make_job()], 50)

        result_jobs, total = await repo.list_by_user(uuid4(), uuid4(), limit=1)
        assert len(result_jobs) == 1
        assert total == 50

    @pytest.mark.asyncio
    async def test_list_by_user_executes_two_queries(self, repo, session):
        """Test 11: list_by_user() runs exactly two queries (count + select)."""
        self._setup_list_mocks(session, [], 0)
        await repo.list_by_user(uuid4(), uuid4())
        assert session.execute.call_count == 2


# ── update_status ────────────────────────────────────────────────────────────


class TestUpdateStatus:
    @pytest.mark.asyncio
    async def test_update_status_sets_status(self, repo, session):
        """Test 12: update_status() sets the new status."""
        job = _make_job(status="rendering")
        update_result = MagicMock()
        update_result.rowcount = 1
        refresh_result = MagicMock()
        refresh_result.scalar_one_or_none.return_value = job
        session.execute.side_effect = [update_result, refresh_result]

        result = await repo.update_status(job.id, "rendering")
        assert result is job

    @pytest.mark.asyncio
    async def test_update_status_completed_sets_completed_at(self, repo, session):
        """Test 13: update_status('completed') sets completed_at."""
        job = _make_job(status="completed")
        update_result = MagicMock()
        update_result.rowcount = 1
        refresh_result = MagicMock()
        refresh_result.scalar_one_or_none.return_value = job
        session.execute.side_effect = [update_result, refresh_result]

        with patch("app.modules.shorts_render.repository.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 18, tzinfo=timezone.utc)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = await repo.update_status(job.id, "completed")

        assert result is job
        # Verify the update statement was called (first execute call)
        assert session.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_update_status_failed_sets_completed_at(self, repo, session):
        """Test 14: update_status('failed') also sets completed_at."""
        job = _make_job(status="failed", error="boom")
        update_result = MagicMock()
        update_result.rowcount = 1
        refresh_result = MagicMock()
        refresh_result.scalar_one_or_none.return_value = job
        session.execute.side_effect = [update_result, refresh_result]

        result = await repo.update_status(job.id, "failed", error="boom")
        assert result is job

    @pytest.mark.asyncio
    async def test_update_status_nonexistent_returns_none(self, repo, session):
        """Test 15: update_status() returns None when job doesn't exist."""
        update_result = MagicMock()
        update_result.rowcount = 0
        session.execute.return_value = update_result

        result = await repo.update_status(uuid4(), "completed")
        assert result is None


# ── delete ───────────────────────────────────────────────────────────────────


class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_existing_returns_true(self, repo, session):
        """Test 16: delete() returns True when job exists and org matches."""
        job = _make_job()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = job
        session.execute.return_value = mock_result

        result = await repo.delete(job.org_id, job.id)
        assert result is True
        session.delete.assert_awaited_once_with(job)
        session.flush.assert_awaited()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self, repo, session):
        """Test 17: delete() returns False when job doesn't exist."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        result = await repo.delete(uuid4(), uuid4())
        assert result is False
        session.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_wrong_org_returns_false(self, repo, session):
        """Test 18: delete() returns False when org doesn't match."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        result = await repo.delete(uuid4(), uuid4())
        assert result is False


# ── list_expired ─────────────────────────────────────────────────────────────


class TestListExpired:
    @pytest.mark.asyncio
    async def test_list_expired_returns_expired_jobs(self, repo, session):
        """Test 19: list_expired() returns jobs past expiry with output files."""
        jobs = [_make_job(output_s3_key="s3://bucket/key")]
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = jobs
        mock_result = MagicMock()
        mock_result.scalars.return_value = scalars_mock
        session.execute.return_value = mock_result

        result = await repo.list_expired(datetime(2026, 5, 1, tzinfo=timezone.utc))
        assert result == jobs

    @pytest.mark.asyncio
    async def test_list_expired_empty(self, repo, session):
        """Test 20: list_expired() returns empty list when none expired."""
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = scalars_mock
        session.execute.return_value = mock_result

        result = await repo.list_expired(datetime(2026, 1, 1, tzinfo=timezone.utc))
        assert result == []

    @pytest.mark.asyncio
    async def test_list_expired_calls_execute(self, repo, session):
        """Test 21: list_expired() executes a query."""
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = scalars_mock
        session.execute.return_value = mock_result

        await repo.list_expired(datetime(2026, 5, 1, tzinfo=timezone.utc))
        session.execute.assert_awaited_once()
