"""Phase 4 PR #5a — SQS publish + service-flag tests.

Covers:

* ``sqs_producer.publish_product_track_job`` body shape — legacy flow
  (catalog_entry_id + duration_preset_sec) AND scan_order parent
  flow (mode='scan_order' + wizard fields). The body dict omits
  None-valued fields so the wire stays tight.
* ``ProductScanService.enqueue_scan_order`` publish flag —
  ``auto_shorts_product_v2_publish_scan_order_enabled=False`` skips
  the publish; True calls it; publisher exception → 503 + parent
  marked failed.

NOT in CI allowlist (consistent with the rest of the
test_shorts_auto_product_*.py suite).
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app import sqs_producer
from app.modules.shorts_auto_product.schemas import ScanOrderCreateRequest
from app.modules.shorts_auto_product.service import ProductScanService


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------


def _settings_stub(*, publish_enabled: bool = True):
    s = MagicMock()
    s.auto_shorts_product_v2_enabled = True
    s.auto_shorts_product_v2_rollout_pct = 100
    s.auto_shorts_product_v2_daily_budget_usd = 50.0
    s.auto_shorts_product_v2_max_concurrent_per_org = 3
    s.auto_shorts_product_v2_scan_order_idempotency_seconds = 60
    s.auto_shorts_product_v2_tracker_version = "v1.0"
    s.auto_shorts_product_v2_enumeration_prompt_version = "v1.0"
    s.auto_shorts_product_v2_callback_base_url = "https://api.example.com"
    s.auto_shorts_product_v2_publish_scan_order_enabled = publish_enabled
    return s


def _build_service(*, publish_enabled: bool = True):
    svc = ProductScanService(
        session=MagicMock(),
        settings=_settings_stub(publish_enabled=publish_enabled),
    )
    svc.session.flush = AsyncMock()
    svc.catalog_repo = MagicMock()
    svc.catalog_repo.list_active_by_video = AsyncMock(return_value=[])
    svc.appearance_repo = MagicMock()
    svc.job_repo = MagicMock()
    svc.cost_repo = MagicMock()
    svc.cost_repo.get_today_cost = AsyncMock(return_value=Decimal("0"))
    svc.job_repo.count_active_for_org = AsyncMock(return_value=0)
    svc.job_repo.find_recent_scan_order_duplicate = AsyncMock(return_value=None)

    parent = MagicMock()
    parent.id = uuid4()
    svc.job_repo.create_scan_order_parent = AsyncMock(return_value=parent)
    svc.job_repo.fail = AsyncMock()
    return svc, parent


def _scan_order_body(**overrides):
    defaults = {
        "length_seconds": 60,
        "requested_count": 5,
        "time_range_start_ms": None,
        "time_range_end_ms": None,
        "product_distribution": "single",
        "language": "ko",
        "intent": "commit",
    }
    defaults.update(overrides)
    return ScanOrderCreateRequest(**defaults)


# ======================================================================
# sqs_producer.publish_product_track_job — body shape
# ======================================================================


def _capture_publish_body():
    """Patch the underlying ``_publish`` and capture the body dict
    for inspection."""
    captured = {}

    def fake_publish(queue_name, body, dedup_id):
        captured["queue_name"] = queue_name
        captured["body"] = body
        captured["dedup_id"] = dedup_id

    return captured, fake_publish


def test_publish_legacy_flow_carries_catalog_entry_id(monkeypatch):
    """Legacy single-product path: catalog_entry_id + duration_preset_sec
    set, mode defaults to 'enumerate', no wizard fields in the body."""
    captured, fake = _capture_publish_body()
    monkeypatch.setattr(sqs_producer, "_publish", fake)

    settings = MagicMock()
    settings.queue_backend = "sqs"
    settings.sqs_enabled = True
    monkeypatch.setattr(sqs_producer, "get_settings", lambda: settings)

    catalog_id = uuid4()
    sqs_producer.publish_product_track_job(
        job_id=uuid4(),
        org_id=uuid4(),
        video_id=uuid4(),
        requested_by_user_id=uuid4(),
        tracker_version="v1.0",
        enumeration_prompt_version="v1.0",
        callback_base_url="https://x",
        catalog_entry_id=catalog_id,
        duration_preset_sec=60,
    )

    body = captured["body"]
    assert body["mode"] == "enumerate"
    assert body["catalog_entry_id"] == str(catalog_id)
    assert body["duration_preset_sec"] == 60
    # Wizard fields MUST be absent for legacy senders.
    for k in (
        "length_seconds", "requested_count",
        "time_range_start_ms", "time_range_end_ms",
        "product_distribution", "language", "intent",
    ):
        assert k not in body, f"{k!r} leaked into legacy publish body"


def test_publish_scan_order_flow_carries_wizard_fields(monkeypatch):
    """Wizard parent path: mode='scan_order' + full wizard field set;
    no catalog_entry_id, no duration_preset_sec."""
    captured, fake = _capture_publish_body()
    monkeypatch.setattr(sqs_producer, "_publish", fake)

    settings = MagicMock()
    settings.queue_backend = "sqs"
    settings.sqs_enabled = True
    monkeypatch.setattr(sqs_producer, "get_settings", lambda: settings)

    sqs_producer.publish_product_track_job(
        job_id=uuid4(),
        org_id=uuid4(),
        video_id=uuid4(),
        requested_by_user_id=uuid4(),
        tracker_version="v1.0",
        enumeration_prompt_version="v1.0",
        callback_base_url="https://x",
        mode="scan_order",
        length_seconds=60,
        requested_count=5,
        time_range_start_ms=0,
        time_range_end_ms=600_000,
        product_distribution="single",
        language="ko",
        intent="commit",
    )

    body = captured["body"]
    assert body["mode"] == "scan_order"
    assert body["length_seconds"] == 60
    assert body["requested_count"] == 5
    assert body["time_range_start_ms"] == 0
    assert body["time_range_end_ms"] == 600_000
    assert body["product_distribution"] == "single"
    assert body["language"] == "ko"
    assert body["intent"] == "commit"
    # Legacy fields MUST be absent for scan_order parents.
    assert "catalog_entry_id" not in body
    assert "duration_preset_sec" not in body


def test_publish_skips_when_queue_disabled(monkeypatch):
    """Off-switch — neither RabbitMQ nor SQS enabled → no-op."""
    captured, fake = _capture_publish_body()
    monkeypatch.setattr(sqs_producer, "_publish", fake)

    settings = MagicMock()
    settings.queue_backend = "sqs"
    settings.sqs_enabled = False
    monkeypatch.setattr(sqs_producer, "get_settings", lambda: settings)

    sqs_producer.publish_product_track_job(
        job_id=uuid4(),
        org_id=uuid4(),
        video_id=uuid4(),
        requested_by_user_id=uuid4(),
        tracker_version="v1.0",
        enumeration_prompt_version="v1.0",
        callback_base_url="https://x",
        mode="scan_order",
        length_seconds=60,
        requested_count=5,
    )
    assert captured == {}


# ======================================================================
# ProductScanService.enqueue_scan_order — publish flag
# ======================================================================


@pytest.mark.asyncio
async def test_enqueue_scan_order_publishes_when_flag_on():
    svc, parent = _build_service(publish_enabled=True)
    org_id = uuid4()
    video_id = uuid4()
    user_id = uuid4()

    with patch(
        "app.modules.shorts_auto_product.service.sqs_producer."
        "publish_product_track_job"
    ) as mock_publish:
        resp = await svc.enqueue_scan_order(
            org_id=org_id,
            video_id=video_id,
            user_id=user_id,
            body=_scan_order_body(),
        )

    assert resp.parent_job_id == parent.id
    mock_publish.assert_called_once()
    call_kwargs = mock_publish.call_args.kwargs
    assert call_kwargs["mode"] == "scan_order"
    assert call_kwargs["job_id"] == parent.id
    assert call_kwargs["length_seconds"] == 60
    assert call_kwargs["requested_count"] == 5
    assert "catalog_entry_id" not in call_kwargs or call_kwargs["catalog_entry_id"] is None


@pytest.mark.asyncio
async def test_enqueue_scan_order_skips_publish_when_flag_off():
    svc, parent = _build_service(publish_enabled=False)

    with patch(
        "app.modules.shorts_auto_product.service.sqs_producer."
        "publish_product_track_job"
    ) as mock_publish:
        resp = await svc.enqueue_scan_order(
            org_id=uuid4(),
            video_id=uuid4(),
            user_id=uuid4(),
            body=_scan_order_body(),
        )

    assert resp.parent_job_id == parent.id
    # Parent row created but publish skipped — wizard UI shows
    # 'queued' until the operator flips the flag on.
    mock_publish.assert_not_called()


@pytest.mark.asyncio
async def test_enqueue_scan_order_503_when_publish_fails():
    """Publisher raises (e.g. SQS outage) → service marks parent as
    failed and raises 503 so the wizard UI can render a retry
    affordance.
    """
    svc, parent = _build_service(publish_enabled=True)

    with patch(
        "app.modules.shorts_auto_product.service.sqs_producer."
        "publish_product_track_job",
        side_effect=RuntimeError("sqs offline"),
    ):
        with pytest.raises(HTTPException) as exc:
            await svc.enqueue_scan_order(
                org_id=uuid4(),
                video_id=uuid4(),
                user_id=uuid4(),
                body=_scan_order_body(),
            )

    assert exc.value.status_code == 503
    # Parent row was marked failed via repo.fail.
    svc.job_repo.fail.assert_awaited_once()
    fail_kwargs = svc.job_repo.fail.await_args.kwargs
    assert fail_kwargs["job_id"] == parent.id
    assert fail_kwargs["error_code"] == "internal_error"
