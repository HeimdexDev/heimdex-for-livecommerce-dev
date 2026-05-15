"""Validator tests for shorts_auto_product API request/response schemas.

These are the API boundary types — distinct from
``heimdex_media_contracts.product`` (which is the worker boundary,
covered by tests in the contracts repo). Light coverage here because
pydantic enforces most invariants; we test the spots where validation
choices have product significance.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.shorts_auto_product.schemas import (
    CatalogProductSummary,
    ClipRequest,
    ClipResponse,
    JobStatusResponse,
    ProductCatalogResponse,
    ProductV2AvailabilityFragment,
    RescanResponse,
    ScanOrderCreateRequest,
    ScanRequest,
    ScanResponse,
)


class TestScanRequest:
    def test_default_preset_is_60(self):
        # Plan §1: 60s default matches Reels/Shorts/TikTok native length.
        assert ScanRequest().duration_preset_sec == 60

    def test_thirty_sixty_ninety_allowed(self):
        for preset in (30, 60, 90):
            assert ScanRequest(duration_preset_sec=preset).duration_preset_sec == preset

    def test_off_preset_rejected(self):
        # Plan §1 locks the preset set. Not adding 45 / 120 etc.
        # without an explicit decision — guards against well-meaning
        # "feature creep" PRs.
        for preset in (15, 45, 75, 120, 0, -30):
            with pytest.raises(ValidationError):
                ScanRequest(duration_preset_sec=preset)


class TestClipRequest:
    def test_same_preset_set_as_scan(self):
        # Two request types with the same preset constraint — the
        # locked decision applies to both.
        for preset in (30, 60, 90):
            ClipRequest(duration_preset_sec=preset)
        for preset in (45, 120):
            with pytest.raises(ValidationError):
                ClipRequest(duration_preset_sec=preset)


class TestProductCatalogResponse:
    def test_empty_catalog_roundtrip(self):
        r = ProductCatalogResponse(video_id=uuid4(), scan_status="never")
        roundtrip = ProductCatalogResponse.model_validate_json(r.model_dump_json())
        assert roundtrip == r
        assert roundtrip.products == []
        assert roundtrip.scan_job_id is None

    def test_in_progress_carries_scan_job_id(self):
        scan_job_id = uuid4()
        r = ProductCatalogResponse(
            video_id=uuid4(),
            scan_status="in_progress",
            scan_job_id=scan_job_id,
        )
        assert r.scan_job_id == scan_job_id

    def test_unknown_scan_status_rejected(self):
        with pytest.raises(ValidationError):
            ProductCatalogResponse(
                video_id=uuid4(),
                scan_status="not-a-real-status",  # type: ignore[arg-type]
            )

    def test_populated_catalog(self):
        product = CatalogProductSummary(
            catalog_entry_id=uuid4(),
            label="핑크 세럼 병",
            canonical_crop_url="https://s3.example/products/abc/canonical.jpg",
            enumeration_confidence=0.87,
            prominence_score=0.42,
            has_track_data=True,
            appearance_count=4,
            total_appearance_seconds=28.5,
        )
        r = ProductCatalogResponse(
            video_id=uuid4(),
            scan_status="complete",
            enumeration_version="v1.0",
            enumeration_prompt_version="v1.0",
            products=[product],
        )
        roundtrip = ProductCatalogResponse.model_validate_json(r.model_dump_json())
        assert roundtrip == r


class TestCatalogProductSummary:
    def test_no_track_data_implies_null_counts(self):
        # has_track_data=False → counts/seconds should be None;
        # there's no zero-vs-null ambiguity in the UI this way.
        p = CatalogProductSummary(
            catalog_entry_id=uuid4(),
            label="x",
            canonical_crop_url="https://x",
            enumeration_confidence=0.5,
            prominence_score=0.5,
            has_track_data=False,
        )
        assert p.appearance_count is None
        assert p.total_appearance_seconds is None

    def test_negative_appearance_count_rejected(self):
        with pytest.raises(ValidationError):
            CatalogProductSummary(
                catalog_entry_id=uuid4(),
                label="x",
                canonical_crop_url="https://x",
                enumeration_confidence=0.5,
                prominence_score=0.5,
                has_track_data=True,
                appearance_count=-1,
            )


class TestJobStatusResponse:
    def _job(self, **overrides):
        kwargs = dict(
            job_id=uuid4(),
            kind="enumeration",
            stage="enumerating",
            progress_pct=42,
            cost_usd_estimate=Decimal("0.0500"),
        )
        kwargs.update(overrides)
        return JobStatusResponse(**kwargs)

    def test_basic_roundtrip(self):
        r = self._job()
        assert JobStatusResponse.model_validate_json(r.model_dump_json()) == r

    def test_progress_clamped(self):
        with pytest.raises(ValidationError):
            self._job(progress_pct=101)
        with pytest.raises(ValidationError):
            self._job(progress_pct=-1)

    def test_unknown_stage_rejected(self):
        with pytest.raises(ValidationError):
            self._job(stage="not-a-real-stage")

    def test_terminal_with_error_code(self):
        r = self._job(
            stage="failed",
            error_code="no_products_detected",
            error_message="0 products met the inclusion threshold.",
        )
        assert r.error_code == "no_products_detected"

    def test_unknown_error_code_rejected(self):
        with pytest.raises(ValidationError):
            self._job(stage="failed", error_code="totally-new-code", error_message="x")

    def test_decimal_cost_roundtrips(self):
        # Pydantic should preserve Decimal precision through JSON.
        r = self._job(cost_usd_estimate=Decimal("1.2345"))
        roundtrip = JobStatusResponse.model_validate_json(r.model_dump_json())
        assert roundtrip.cost_usd_estimate == Decimal("1.2345")


class TestScanAndClipResponse:
    def test_scan_default_not_deduped(self):
        assert ScanResponse(job_id=uuid4()).deduped is False

    def test_clip_render_job_id_optional(self):
        # Render job id is None until the track worker enqueues the
        # render — frontend polls jobs/{job_id} for the transition.
        r = ClipResponse(job_id=uuid4())
        assert r.render_job_id is None


class TestAvailabilityFragment:
    def test_remaining_pct_clamps(self):
        # Service should clamp to [0, 100] but the schema enforces it
        # at the boundary as a defense in depth.
        with pytest.raises(ValidationError):
            ProductV2AvailabilityFragment(
                product_v2_enabled=True,
                product_v2_in_rollout=True,
                product_v2_daily_budget_remaining_pct=101,
                product_v2_duration_presets_sec=[30, 60, 90],
            )
        with pytest.raises(ValidationError):
            ProductV2AvailabilityFragment(
                product_v2_enabled=True,
                product_v2_in_rollout=True,
                product_v2_daily_budget_remaining_pct=-1,
                product_v2_duration_presets_sec=[30, 60, 90],
            )


class TestRescanResponse:
    def test_invalidated_count_non_negative(self):
        with pytest.raises(ValidationError):
            RescanResponse(job_id=uuid4(), invalidated_count=-1)

    def test_zero_invalidated_ok(self):
        # First-ever rescan on a video with no catalog → 0 invalidated.
        r = RescanResponse(job_id=uuid4(), invalidated_count=0)
        assert r.invalidated_count == 0


class TestScanOrderCreateRequest:
    """Wizard parent body — Phase 4 + product-select extension."""

    _BASE = {
        "length_seconds": 60,
        "requested_count": 5,
        "product_distribution": "single",
        "language": "ko",
    }

    def test_catalog_entry_id_is_optional(self):
        # Backward compat: existing wizard submissions don't carry the
        # field; default to None (whole-catalog round-robin).
        body = ScanOrderCreateRequest(**self._BASE)
        assert body.catalog_entry_id is None

    def test_catalog_entry_id_accepts_uuid(self):
        # Product-select step output: a UUID narrows the worker's
        # catalog fetch to that single entry.
        eid = uuid4()
        body = ScanOrderCreateRequest(catalog_entry_id=eid, **self._BASE)
        assert body.catalog_entry_id == eid

    def test_catalog_entry_id_rejects_non_uuid_string(self):
        # Pydantic enforces UUID shape; a stringly-typed sentinel
        # would otherwise silently slip through to the SQS body and
        # fail at the worker.
        with pytest.raises(ValidationError):
            ScanOrderCreateRequest(catalog_entry_id="not-a-uuid", **self._BASE)
