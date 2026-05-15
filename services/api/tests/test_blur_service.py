"""Service-layer tests for BlurService.

Exercises the guard conditions that prevent runaway cost and duplicate
work — ``BLUR_ENABLED`` gate, missing proxy, concurrency cap, dedupe
window, SQS publish failure rollback, and the cancel state machine.

All dependencies are mocked; no DB, no SQS, no S3.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.blur.models import (
    BLUR_STATUS_DONE,
    BLUR_STATUS_FAILED,
    BLUR_STATUS_QUEUED,
    BLUR_STATUS_RUNNING,
    BlurJob,
)
from app.modules.blur.schemas import CreateBlurJobRequest
from app.modules.blur.service import BlurService, compute_options_hash
from heimdex_media_contracts.blur import BlurOptions


def _settings(
    *,
    blur_enabled: bool = True,
    max_active: int = 5,
    sqs_enabled: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        blur_enabled=blur_enabled,
        blur_max_active_per_org=max_active,
        blur_lease_seconds=1800,
        blur_daily_budget_usd_per_org=50.0,
        sqs_enabled=sqs_enabled,
        sqs_blur_queue_url="https://sqs.test/blur",
        drive_s3_bucket="heimdex-drive",
    )


def _drive_file(**overrides):
    defaults = dict(
        id=uuid4(),
        org_id=uuid4(),
        video_id="gd_testvideo",
        proxy_s3_key="proxies/gd_testvideo/proxy.mp4",
        google_file_id="gfile",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.fixture
def repo():
    r = MagicMock()
    r.session = AsyncMock()
    r.create = AsyncMock()
    r.find_recent_duplicate = AsyncMock(return_value=None)
    r.count_active_for_org = AsyncMock(return_value=0)
    r.get_by_id = AsyncMock()
    r.list_by_file = AsyncMock()
    r.mark_cancelled_if_queued = AsyncMock()
    return r


@pytest.fixture
def drive_file_repo():
    r = MagicMock()
    r.get_by_id = AsyncMock()
    return r


@pytest.fixture
def service(repo, drive_file_repo):
    return BlurService(repo, drive_file_repo)


# ---------- create_blur_job ----------

class TestCreate:
    @pytest.mark.asyncio
    async def test_disabled_raises_404(self, service, drive_file_repo):
        drive_file_repo.get_by_id.return_value = _drive_file()
        with patch("app.modules.blur.service.get_settings",
                   return_value=_settings(blur_enabled=False)):
            with pytest.raises(HTTPException) as exc_info:
                await service.create_blur_job(
                    org_id=uuid4(), user_id=uuid4(), file_id=uuid4(),
                    payload=CreateBlurJobRequest(),
                )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_missing_drive_file_raises_404(
        self, service, drive_file_repo, repo,
    ):
        drive_file_repo.get_by_id.return_value = None
        with patch("app.modules.blur.service.get_settings",
                   return_value=_settings()):
            with pytest.raises(HTTPException) as exc_info:
                await service.create_blur_job(
                    org_id=uuid4(), user_id=uuid4(), file_id=uuid4(),
                    payload=CreateBlurJobRequest(),
                )
        assert exc_info.value.status_code == 404
        repo.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_proxy_raises_409(
        self, service, drive_file_repo, repo,
    ):
        drive_file_repo.get_by_id.return_value = _drive_file(proxy_s3_key=None)
        with patch("app.modules.blur.service.get_settings",
                   return_value=_settings()):
            with pytest.raises(HTTPException) as exc_info:
                await service.create_blur_job(
                    org_id=uuid4(), user_id=uuid4(), file_id=uuid4(),
                    payload=CreateBlurJobRequest(),
                )
        assert exc_info.value.status_code == 409
        repo.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_concurrency_cap_rejects(
        self, service, drive_file_repo, repo,
    ):
        drive_file_repo.get_by_id.return_value = _drive_file()
        repo.count_active_for_org.return_value = 5  # == cap
        with patch("app.modules.blur.service.get_settings",
                   return_value=_settings(max_active=5)):
            with pytest.raises(HTTPException) as exc_info:
                await service.create_blur_job(
                    org_id=uuid4(), user_id=uuid4(), file_id=uuid4(),
                    payload=CreateBlurJobRequest(),
                )
        assert exc_info.value.status_code == 429
        repo.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_dedupe_returns_existing(
        self, service, drive_file_repo, repo,
    ):
        drive_file_repo.get_by_id.return_value = _drive_file()
        existing = MagicMock(spec=BlurJob)
        for k, v in dict(
            id=uuid4(),
            file_id=uuid4(),
            video_id="gd_testvideo",
            requested_by=uuid4(),
            status=BLUR_STATUS_QUEUED,
            options={"do_faces": True},
            source_kind="proxy",
            blurred_s3_key=None,
            manifest_s3_key=None,
            detections_summary=None,
            error=None,
            requested_at=datetime.now(timezone.utc),
            started_at=None,
            completed_at=None,
        ).items():
            setattr(existing, k, v)
        repo.find_recent_duplicate.return_value = existing

        with patch("app.modules.blur.service.get_settings",
                   return_value=_settings()):
            result = await service.create_blur_job(
                org_id=uuid4(), user_id=uuid4(), file_id=uuid4(),
                payload=CreateBlurJobRequest(),
            )
        # Should return the existing job, not create a new one.
        repo.create.assert_not_called()
        assert result.id == existing.id

    @pytest.mark.asyncio
    async def test_publish_failure_marks_failed(
        self, service, drive_file_repo, repo,
    ):
        drive_file_repo.get_by_id.return_value = _drive_file()
        fresh_job = MagicMock(spec=BlurJob)
        for k, v in dict(
            id=uuid4(),
            file_id=uuid4(),
            video_id="gd_testvideo",
            requested_by=uuid4(),
            status=BLUR_STATUS_QUEUED,
            options={},
            source_kind="proxy",
            blurred_s3_key=None,
            manifest_s3_key=None,
            detections_summary=None,
            error=None,
            requested_at=datetime.now(timezone.utc),
            started_at=None,
            completed_at=None,
        ).items():
            setattr(fresh_job, k, v)
        repo.create.return_value = fresh_job

        with patch("app.modules.blur.service.get_settings",
                   return_value=_settings()), \
             patch("app.sqs_producer.publish_blur_job",
                   side_effect=RuntimeError("sqs down")):
            result = await service.create_blur_job(
                org_id=uuid4(), user_id=uuid4(), file_id=uuid4(),
                payload=CreateBlurJobRequest(),
            )
        # Service must surface the failure via the row state, not via
        # a 500 — users see `status=failed` + `error=...`.
        assert result.status == BLUR_STATUS_FAILED
        assert "Failed to enqueue" in (result.error or "")


# ---------- cancel_blur_job ----------

class TestCancel:
    @pytest.mark.asyncio
    async def test_cancel_missing_raises_404(self, service, repo):
        repo.get_by_id.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            await service.cancel_blur_job(org_id=uuid4(), job_id=uuid4())
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_running_rejected_409(self, service, repo):
        running = MagicMock(spec=BlurJob)
        running.status = BLUR_STATUS_RUNNING
        repo.get_by_id.return_value = running
        with pytest.raises(HTTPException) as exc_info:
            await service.cancel_blur_job(org_id=uuid4(), job_id=uuid4())
        assert exc_info.value.status_code == 409
        repo.mark_cancelled_if_queued.assert_not_called()

    @pytest.mark.asyncio
    async def test_cancel_terminal_rejected_409(self, service, repo):
        done = MagicMock(spec=BlurJob)
        done.status = BLUR_STATUS_DONE
        repo.get_by_id.return_value = done
        with pytest.raises(HTTPException) as exc_info:
            await service.cancel_blur_job(org_id=uuid4(), job_id=uuid4())
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_cancel_race_lost_409(self, service, repo):
        queued = MagicMock(spec=BlurJob)
        queued.status = BLUR_STATUS_QUEUED
        repo.get_by_id.return_value = queued
        repo.mark_cancelled_if_queued.return_value = False  # raced
        with pytest.raises(HTTPException) as exc_info:
            await service.cancel_blur_job(org_id=uuid4(), job_id=uuid4())
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_cancel_success(self, service, repo):
        queued = MagicMock(spec=BlurJob)
        for k, v in dict(
            id=uuid4(),
            file_id=uuid4(),
            video_id="v",
            requested_by=uuid4(),
            status=BLUR_STATUS_QUEUED,
            options={},
            source_kind="proxy",
            blurred_s3_key=None,
            manifest_s3_key=None,
            detections_summary=None,
            error=None,
            requested_at=datetime.now(timezone.utc),
            started_at=None,
            completed_at=None,
        ).items():
            setattr(queued, k, v)
        cancelled = MagicMock(spec=BlurJob)
        for k, v in dict(
            id=queued.id,
            file_id=queued.file_id,
            video_id=queued.video_id,
            requested_by=queued.requested_by,
            status="cancelled",
            options={},
            source_kind="proxy",
            blurred_s3_key=None,
            manifest_s3_key=None,
            detections_summary=None,
            error=None,
            requested_at=queued.requested_at,
            started_at=None,
            completed_at=datetime.now(timezone.utc),
        ).items():
            setattr(cancelled, k, v)
        repo.get_by_id.side_effect = [queued, cancelled]
        repo.mark_cancelled_if_queued.return_value = True

        result = await service.cancel_blur_job(org_id=uuid4(), job_id=uuid4())
        assert result.status == "cancelled"


# ---------- compute_options_hash ----------

class TestOptionsHash:
    def test_deterministic(self):
        a = BlurOptions()
        b = BlurOptions()
        assert compute_options_hash(a) == compute_options_hash(b)

    def test_differs_on_change(self):
        a = BlurOptions()
        b = BlurOptions(owl_stride=10)
        assert compute_options_hash(a) != compute_options_hash(b)

    def test_hex_length(self):
        assert len(compute_options_hash(BlurOptions())) == 64
