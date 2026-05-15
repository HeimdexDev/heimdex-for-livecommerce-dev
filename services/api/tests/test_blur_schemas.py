"""Pydantic unit tests for the app-side blur schemas.

Covers the public request/response contracts and the three internal
worker-callback payloads. No I/O, no DB — mirrors
``test_shorts_render_schemas.py`` in shape.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from heimdex_media_contracts.blur import BlurOptions

from app.modules.blur.schemas import (
    BlurJobClaim,
    BlurJobCompletePayload,
    BlurJobHeartbeatPayload,
    BlurJobListResponse,
    BlurJobResponse,
    CreateBlurJobRequest,
)


class TestCreateBlurJobRequest:
    def test_empty_body_uses_defaults(self):
        req = CreateBlurJobRequest()
        assert req.source_kind == "proxy"
        assert req.options.do_faces is True
        assert "logo" not in req.options.categories

    def test_custom_options_override(self):
        req = CreateBlurJobRequest(
            options=BlurOptions(
                do_faces=False,
                do_owl=True,
                categories=("license_plate",),
                owl_stride=3,
            ),
        )
        assert req.options.do_faces is False
        assert req.options.categories == ("license_plate",)
        assert req.options.owl_stride == 3

    def test_unknown_source_kind_rejected(self):
        with pytest.raises(ValidationError):
            CreateBlurJobRequest(source_kind="bogus")  # type: ignore[arg-type]

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            CreateBlurJobRequest.model_validate({"options": {}, "bogus": 1})


class TestBlurJobResponse:
    def test_from_attributes(self):
        orm = SimpleNamespace(
            id=uuid4(),
            file_id=uuid4(),
            video_id="v1",
            requested_by=uuid4(),
            status="queued",
            options={"do_faces": True},
            source_kind="proxy",
            blurred_s3_key=None,
            manifest_s3_key=None,
            detections_summary=None,
            error=None,
            requested_at=datetime.now(timezone.utc),
            started_at=None,
            completed_at=None,
        )
        resp = BlurJobResponse.model_validate(orm)
        assert resp.video_id == "v1"
        assert resp.status == "queued"
        assert resp.blurred_s3_key is None

    def test_list_response(self):
        orm = SimpleNamespace(
            id=uuid4(),
            file_id=uuid4(),
            video_id="v1",
            requested_by=uuid4(),
            status="done",
            options={},
            source_kind="proxy",
            blurred_s3_key="blurred/v1/job-1/blurred.mp4",
            manifest_s3_key="blurred/v1/job-1/manifest.json",
            detections_summary={"face": 2},
            error=None,
            requested_at=datetime.now(timezone.utc),
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        resp = BlurJobListResponse(
            items=[BlurJobResponse.model_validate(orm)],
            total=1,
        )
        assert resp.total == 1
        assert resp.items[0].detections_summary == {"face": 2}


class TestInternalPayloads:
    def test_claim_roundtrip(self):
        c = BlurJobClaim(
            id=uuid4(),
            org_id=uuid4(),
            file_id=uuid4(),
            video_id="v1",
            source_s3_key="proxies/v1/proxy.mp4",
            source_kind="proxy",
            options={"do_faces": True},
            lease_token=uuid4(),
            lease_expires_at=datetime.now(timezone.utc),
        )
        restored = BlurJobClaim.model_validate_json(c.model_dump_json())
        assert restored == c

    def test_complete_requires_lease_token(self):
        with pytest.raises(ValidationError):
            BlurJobCompletePayload.model_validate({"status": "done"})

    def test_complete_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            BlurJobCompletePayload.model_validate({
                "lease_token": str(uuid4()),
                "status": "done",
                "bogus": "field",
            })

    def test_heartbeat_only_lease_token(self):
        p = BlurJobHeartbeatPayload(lease_token=uuid4())
        with pytest.raises(ValidationError):
            BlurJobHeartbeatPayload.model_validate({"other": 1})
        _ = p.lease_token
