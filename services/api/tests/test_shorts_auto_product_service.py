"""Service-layer tests for ProductScanService.

Focus: gating logic (feature flag, rollout, cost cap, concurrency,
idempotency) — these are the spots where a bug silently overcharges
users or leaks budget. Repositories are mocked; this is not an
integration test.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.config import Settings
from app.modules.shorts_auto_product.models import (
    ACTIVE_SCAN_STAGES,
    SCAN_STAGE_ENUMERATING,
    SCAN_STAGE_ENUMERATION_DONE,
    SCAN_STAGE_FAILED,
    SCAN_STAGE_QUEUED,
)
from app.modules.shorts_auto_product.service import (
    ProductScanService,
    _stable_org_bucket,
)


def _settings(**overrides) -> Settings:
    """Build a Settings with v2 enabled at 100% by default; tests
    override individual flags. Avoids env-var pollution by passing
    explicit values."""
    base = dict(
        auto_shorts_product_v2_enabled=True,
        auto_shorts_product_v2_rollout_pct=100,
        auto_shorts_product_v2_daily_budget_usd=50.0,
        auto_shorts_product_v2_max_concurrent_per_org=3,
        auto_shorts_product_v2_max_keyframes_per_video=60,
        auto_shorts_product_v2_duration_presets_sec="30,60,90",
        auto_shorts_product_v2_enumeration_prompt_version="v1.0",
        auto_shorts_product_v2_enumeration_version="v1.0",
        auto_shorts_product_v2_tracker_version="v1.0",
        auto_shorts_product_v2_scan_idempotency_seconds=60,
        auto_shorts_product_v2_callback_base_url="http://api:8000",
    )
    base.update(overrides)
    return Settings(**base)


def _build_service(settings: Settings) -> ProductScanService:
    session = AsyncMock()
    svc = ProductScanService(session=session, settings=settings)
    # Replace the lazily-instantiated repos with mocks so we can
    # assert against them without a real DB.
    svc.catalog_repo = MagicMock()
    svc.appearance_repo = MagicMock()
    svc.job_repo = MagicMock()
    svc.cost_repo = MagicMock()
    # Default async-method behaviors — tests override per case.
    svc.cost_repo.get_today_cost = AsyncMock(return_value=Decimal("0"))
    svc.job_repo.find_recent_duplicate = AsyncMock(return_value=None)
    svc.job_repo.find_latest_enumeration_for_video = AsyncMock(return_value=None)
    svc.job_repo.count_active_for_org = AsyncMock(return_value=0)
    svc.catalog_repo.get = AsyncMock(return_value=None)
    return svc


# ---------- _stable_org_bucket ----------

class TestStableOrgBucket:
    def test_deterministic(self):
        org_id = uuid4()
        a = _stable_org_bucket(org_id)
        b = _stable_org_bucket(org_id)
        assert a == b

    def test_in_zero_to_one_hundred(self):
        for _ in range(50):
            assert 0 <= _stable_org_bucket(uuid4()) < 100

    def test_distribution_roughly_uniform(self):
        # Loose upper bound — across 1000 random orgs, no single
        # bucket should exceed ~3% of population. This catches a
        # broken hash that always returns 0 / 50 / etc.
        from collections import Counter
        counts = Counter(_stable_org_bucket(uuid4()) for _ in range(1000))
        max_share = max(counts.values()) / 1000
        assert max_share < 0.05


# ---------- feature flag gate ----------

@pytest.mark.asyncio
async def test_disabled_returns_404():
    svc = _build_service(_settings(auto_shorts_product_v2_enabled=False))
    with pytest.raises(HTTPException) as exc:
        await svc.list_products(org_id=uuid4(), video_id=uuid4())
    assert exc.value.status_code == 404
    assert "not enabled" in exc.value.detail


@pytest.mark.asyncio
async def test_zero_rollout_returns_404():
    # rollout_pct=0 means no orgs are in. Even with enabled=True,
    # the user should get 404 — this is what gates staging-only soak.
    svc = _build_service(_settings(auto_shorts_product_v2_rollout_pct=0))
    with pytest.raises(HTTPException) as exc:
        await svc.list_products(org_id=uuid4(), video_id=uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_full_rollout_admits_all_orgs():
    svc = _build_service(_settings(auto_shorts_product_v2_rollout_pct=100))
    svc.catalog_repo.list_active_by_video = AsyncMock(return_value=[])
    # Mock S3 presigner so the test stays unit-level.
    import app.storage.s3 as s3_mod
    s3_mod.S3Client = MagicMock(  # type: ignore[attr-defined]
        return_value=MagicMock(
            generate_presigned_url_async=AsyncMock(return_value="https://x"),
        ),
    )
    response = await svc.list_products(org_id=uuid4(), video_id=uuid4())
    assert response.scan_status == "never"


def test_partial_rollout_is_org_stable():
    # An org that the bucket places at 99 must NOT be admitted at
    # rollout_pct=50 — same org, same answer across calls. Test the
    # gating function directly (no S3/DB) so the bucket→admit mapping
    # is the only thing under test.
    svc_50 = _build_service(_settings(auto_shorts_product_v2_rollout_pct=50))
    for _ in range(50):
        org_id = uuid4()
        bucket = _stable_org_bucket(org_id)
        if bucket < 50:
            # Should NOT raise.
            svc_50._require_enabled_for_org(org_id)
        else:
            with pytest.raises(HTTPException) as exc:
                svc_50._require_enabled_for_org(org_id)
            assert exc.value.status_code == 404


# ---------- cost cap ----------

@pytest.mark.asyncio
async def test_cost_cap_blocks_scan():
    svc = _build_service(_settings(auto_shorts_product_v2_daily_budget_usd=10.0))
    svc.cost_repo.get_today_cost = AsyncMock(return_value=Decimal("10.0"))
    with pytest.raises(HTTPException) as exc:
        await svc.enqueue_scan(
            org_id=uuid4(),
            video_id=uuid4(),
            user_id=uuid4(),
            duration_preset_sec=60,
        )
    assert exc.value.status_code == 402


@pytest.mark.asyncio
async def test_cost_under_cap_proceeds():
    svc = _build_service(_settings(auto_shorts_product_v2_daily_budget_usd=10.0))
    svc.cost_repo.get_today_cost = AsyncMock(return_value=Decimal("9.99"))
    fake_job = MagicMock(id=uuid4())
    svc.job_repo.create_enumeration_job = AsyncMock(return_value=fake_job)
    # Stub publish so we don't hit boto3.
    import app.sqs_producer as sqs_producer
    sqs_producer.publish_product_enumerate_job = MagicMock()
    response = await svc.enqueue_scan(
        org_id=uuid4(),
        video_id=uuid4(),
        user_id=uuid4(),
        duration_preset_sec=60,
    )
    assert response.deduped is False
    assert response.job_id == fake_job.id


# ---------- concurrency cap ----------

@pytest.mark.asyncio
async def test_concurrency_cap_returns_429():
    svc = _build_service(_settings(auto_shorts_product_v2_max_concurrent_per_org=3))
    svc.job_repo.count_active_for_org = AsyncMock(return_value=3)
    with pytest.raises(HTTPException) as exc:
        await svc.enqueue_scan(
            org_id=uuid4(),
            video_id=uuid4(),
            user_id=uuid4(),
            duration_preset_sec=60,
        )
    assert exc.value.status_code == 429
    assert "too many active" in exc.value.detail


# ---------- idempotency ----------

@pytest.mark.asyncio
async def test_idempotency_short_circuits():
    """Same (video, user) within window → return existing job_id and
    skip the create + publish path entirely."""
    existing = MagicMock(id=uuid4())
    svc = _build_service(_settings())
    svc.job_repo.find_recent_duplicate = AsyncMock(return_value=existing)
    svc.job_repo.create_enumeration_job = AsyncMock()
    # Should NOT touch publish or create.
    response = await svc.enqueue_scan(
        org_id=uuid4(),
        video_id=uuid4(),
        user_id=uuid4(),
        duration_preset_sec=60,
    )
    assert response.deduped is True
    assert response.job_id == existing.id
    svc.job_repo.create_enumeration_job.assert_not_called()

# ---------- completion signal  ----------

@pytest.mark.asyncio
async def test_completed_enumeration_short_circuits():
    svc = _build_service(_settings())
    done = MagicMock(id=uuid4(), stage=SCAN_STAGE_ENUMERATION_DONE)
    svc.job_repo.find_latest_enumeration_for_video = AsyncMock(return_value=done)
    svc.job_repo.create_enumeration_job = AsyncMock()
    import app.sqs_producer as sqs_producer
    sqs_producer.publish_product_enumerate_job = MagicMock()
    resp = await svc.enqueue_scan(
        org_id=uuid4(), video_id=uuid4(), user_id=uuid4(),
        duration_preset_sec=60,
    )
    assert resp.deduped is True
    assert resp.job_id == done.id
    svc.job_repo.create_enumeration_job.assert_not_called()
    sqs_producer.publish_product_enumerate_job.assert_not_called()


@pytest.mark.asyncio
async def test_failed_enumeration_still_rescans():
    svc = _build_service(_settings())
    failed = MagicMock(id=uuid4(), stage=SCAN_STAGE_FAILED)
    svc.job_repo.find_latest_enumeration_for_video = AsyncMock(return_value=failed)
    fake_job = MagicMock(id=uuid4())
    svc.job_repo.create_enumeration_job = AsyncMock(return_value=fake_job)
    import app.sqs_producer as sqs_producer
    sqs_producer.publish_product_enumerate_job = MagicMock()
    resp = await svc.enqueue_scan(
        org_id=uuid4(), video_id=uuid4(), user_id=uuid4(),
        duration_preset_sec=60,
    )
    assert resp.deduped is False
    assert resp.job_id == fake_job.id
    svc.job_repo.create_enumeration_job.assert_called_once()


@pytest.mark.asyncio
async def test_rescan_bypasses_completion_guard():
    svc = _build_service(_settings())
    svc.catalog_repo.invalidate_video_catalog = AsyncMock(return_value=7)
    fake_job = MagicMock(id=uuid4())
    svc.job_repo.create_enumeration_job = AsyncMock(return_value=fake_job)
    svc.job_repo.find_latest_enumeration_for_video = AsyncMock(
        return_value=MagicMock(id=uuid4(), stage=SCAN_STAGE_ENUMERATION_DONE),
    )
    import app.sqs_producer as sqs_producer
    sqs_producer.publish_product_enumerate_job = MagicMock()
    resp = await svc.rescan(
        org_id=uuid4(), video_id=uuid4(), user_id=uuid4(),
        duration_preset_sec=60,
    )
    svc.job_repo.create_enumeration_job.assert_called_once()
    assert resp.invalidated_count == 7
    assert resp.job_id == fake_job.id


# ---------- catalog entry not found ----------

@pytest.mark.asyncio
async def test_clip_404_when_catalog_entry_missing():
    svc = _build_service(_settings())
    svc.catalog_repo.get = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc:
        await svc.enqueue_clip(
            org_id=uuid4(),
            video_id=uuid4(),
            catalog_entry_id=uuid4(),
            user_id=uuid4(),
            duration_preset_sec=60,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_clip_404_when_catalog_entry_in_other_video():
    """Cross-video catalog access — even within the same org — must
    not bypass the per-video boundary in v1."""
    svc = _build_service(_settings())
    foreign_video = uuid4()
    request_video = uuid4()
    entry = MagicMock()
    entry.video_id = foreign_video
    entry.rejected_at = None
    svc.catalog_repo.get = AsyncMock(return_value=entry)
    with pytest.raises(HTTPException) as exc:
        await svc.enqueue_clip(
            org_id=uuid4(),
            video_id=request_video,
            catalog_entry_id=uuid4(),
            user_id=uuid4(),
            duration_preset_sec=60,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_clip_404_when_catalog_entry_rejected():
    svc = _build_service(_settings())
    video_id = uuid4()
    entry = MagicMock()
    entry.video_id = video_id
    entry.rejected_at = "2026-04-29T00:00:00Z"  # truthy
    svc.catalog_repo.get = AsyncMock(return_value=entry)
    with pytest.raises(HTTPException) as exc:
        await svc.enqueue_clip(
            org_id=uuid4(),
            video_id=video_id,
            catalog_entry_id=uuid4(),
            user_id=uuid4(),
            duration_preset_sec=60,
        )
    assert exc.value.status_code == 404


# ---------- availability ----------

@pytest.mark.asyncio
async def test_availability_remaining_pct_at_full_cap():
    svc = _build_service(_settings(auto_shorts_product_v2_daily_budget_usd=50.0))
    svc.cost_repo.get_today_cost = AsyncMock(return_value=Decimal("50.0"))
    fragment = await svc.availability_fragment(org_id=uuid4())
    assert fragment.product_v2_daily_budget_remaining_pct == 0


@pytest.mark.asyncio
async def test_availability_remaining_pct_at_no_spend():
    svc = _build_service(_settings(auto_shorts_product_v2_daily_budget_usd=50.0))
    svc.cost_repo.get_today_cost = AsyncMock(return_value=Decimal("0"))
    fragment = await svc.availability_fragment(org_id=uuid4())
    assert fragment.product_v2_daily_budget_remaining_pct == 100


@pytest.mark.asyncio
async def test_availability_presets_parsed():
    svc = _build_service(_settings(
        auto_shorts_product_v2_duration_presets_sec="30,60,90",
    ))
    fragment = await svc.availability_fragment(org_id=uuid4())
    assert fragment.product_v2_duration_presets_sec == [30, 60, 90]
