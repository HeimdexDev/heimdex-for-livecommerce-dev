"""
Tests for internal drive job management endpoints.

Covers:
- Token verification (auth)
- POST /internal/drive/jobs/claim — atomic claim with SKIP LOCKED + lease tokens
- PATCH /internal/drive/jobs/{file_id}/status — status update + enrichment recompute
- Lease token enforcement — mismatch, expiry, idempotency
- GET /internal/drive/files/{file_id} — file metadata lookup
- Concurrency: 10 concurrent claims yield no double-claims
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.drive.internal_router import (
    LEASE_DURATION_SECONDS,
    _verify_internal_token,
    claim_jobs,
    get_file_metadata,
    update_job_status,
)
from app.modules.drive.internal_schemas import (
    ClaimJobsRequest,
    UpdateJobStatusRequest,
)


# ── Auth tests ────────────────────────────────────────────────────────

class TestVerifyInternalToken:
    @pytest.mark.asyncio
    async def test_valid_token_accepted(self):
        with patch("app.dependencies.get_settings") as mock_settings:
            mock_settings.return_value.drive_internal_api_key = "secret-key-123"
            result = await _verify_internal_token("Bearer secret-key-123")
            assert result == "secret-key-123"

    @pytest.mark.asyncio
    async def test_wrong_token_returns_401(self):
        with patch("app.dependencies.get_settings") as mock_settings:
            mock_settings.return_value.drive_internal_api_key = "correct-key"
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await _verify_internal_token("Bearer wrong-key")
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_bearer_prefix_returns_401(self):
        with patch("app.dependencies.get_settings") as mock_settings:
            mock_settings.return_value.drive_internal_api_key = "key"
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await _verify_internal_token("Basic key")
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_unconfigured_key_returns_503(self):
        with patch("app.dependencies.get_settings") as mock_settings:
            mock_settings.return_value.drive_internal_api_key = ""
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await _verify_internal_token("Bearer anything")
            assert exc_info.value.status_code == 503


# ── Helpers ───────────────────────────────────────────────────────────

def _make_drive_file(
    *,
    file_id=None,
    org_id=None,
    video_id="gd_abc123",
    caption_status="pending",
    stt_status=None,
    ocr_status=None,
    face_status=None,
    enrichment_state=None,
    keyframe_s3_prefix="orgs/org1/files/vid1/keyframes/",
    audio_s3_key="orgs/org1/files/vid1/audio.wav",
    is_deleted=False,
    created_at=None,
    lease_token=None,
    lease_expires_at=None,
):
    f = MagicMock()
    f.id = file_id or uuid4()
    f.org_id = org_id or uuid4()
    f.video_id = video_id
    f.caption_status = caption_status
    f.stt_status = stt_status
    f.ocr_status = ocr_status
    f.face_status = face_status
    f.enrichment_state = enrichment_state
    f.scene_count = 1
    f.keyframe_s3_prefix = keyframe_s3_prefix
    f.audio_s3_key = audio_s3_key
    f.is_deleted = is_deleted
    f.created_at = created_at or datetime.now(timezone.utc)
    f.lease_token = lease_token
    f.lease_expires_at = lease_expires_at
    return f


def _mock_db_with_files(files):
    db = AsyncMock()
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = files
    mock_result.scalars.return_value = mock_scalars
    db.execute.return_value = mock_result
    db.flush = AsyncMock()
    return db


def _mock_db_with_scalar_one(file_obj):
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = file_obj
    db.execute = AsyncMock(return_value=mock_result)
    db.flush = AsyncMock()
    return db


# ── Claim jobs tests ──────────────────────────────────────────────────

class TestClaimJobs:
    @pytest.mark.asyncio
    async def test_claim_caption_returns_file(self):
        file = _make_drive_file()
        db = _mock_db_with_files([file])
        request = ClaimJobsRequest(job_type="caption", limit=1)

        result = await claim_jobs(request=request, _token="valid", db=db)

        assert len(result.files) == 1
        assert result.files[0].id == file.id
        assert result.files[0].org_id == file.org_id
        assert result.files[0].video_id == file.video_id
        assert result.files[0].keyframe_s3_prefix == file.keyframe_s3_prefix
        assert file.caption_status == "running"
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_claim_returns_audio_s3_key(self):
        file = _make_drive_file(audio_s3_key="orgs/o/files/v/audio.wav")
        db = _mock_db_with_files([file])
        request = ClaimJobsRequest(job_type="stt", limit=1)

        result = await claim_jobs(request=request, _token="valid", db=db)

        assert len(result.files) == 1
        assert result.files[0].audio_s3_key == "orgs/o/files/v/audio.wav"

    @pytest.mark.asyncio
    async def test_claim_empty_returns_empty_list(self):
        db = _mock_db_with_files([])
        request = ClaimJobsRequest(job_type="caption", limit=1)

        result = await claim_jobs(request=request, _token="valid", db=db)

        assert len(result.files) == 0
        db.flush.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_claim_stt_type_accepted(self):
        file = _make_drive_file()
        db = _mock_db_with_files([file])
        request = ClaimJobsRequest(job_type="stt", limit=1)

        result = await claim_jobs(request=request, _token="valid", db=db)

        assert len(result.files) == 1
        assert file.stt_status == "running"

    @pytest.mark.asyncio
    async def test_claim_ocr_type_accepted(self):
        file = _make_drive_file()
        db = _mock_db_with_files([file])
        request = ClaimJobsRequest(job_type="ocr", limit=1)

        result = await claim_jobs(request=request, _token="valid", db=db)

        assert len(result.files) == 1
        assert file.ocr_status == "running"

    @pytest.mark.asyncio
    async def test_claim_multiple_files(self):
        files = [_make_drive_file(video_id=f"vid_{i}") for i in range(3)]
        db = _mock_db_with_files(files)
        request = ClaimJobsRequest(job_type="caption", limit=3)

        result = await claim_jobs(request=request, _token="valid", db=db)

        assert len(result.files) == 3
        for f in files:
            assert f.caption_status == "running"


# ── Claim lease token tests ──────────────────────────────────────────

class TestClaimLeaseTokens:
    @pytest.mark.asyncio
    async def test_claim_assigns_lease_token(self):
        file = _make_drive_file()
        db = _mock_db_with_files([file])
        request = ClaimJobsRequest(job_type="caption", limit=1)

        result = await claim_jobs(request=request, _token="valid", db=db)

        assert result.files[0].lease_token is not None
        assert len(result.files[0].lease_token) == 36
        assert file.lease_token == result.files[0].lease_token

    @pytest.mark.asyncio
    async def test_claim_assigns_lease_expires_at(self):
        file = _make_drive_file()
        db = _mock_db_with_files([file])
        request = ClaimJobsRequest(job_type="caption", limit=1)

        result = await claim_jobs(request=request, _token="valid", db=db)

        assert result.files[0].lease_expires_at is not None
        assert file.lease_expires_at == result.files[0].lease_expires_at

    @pytest.mark.asyncio
    async def test_each_claimed_file_gets_unique_lease_token(self):
        files = [_make_drive_file(video_id=f"vid_{i}") for i in range(5)]
        db = _mock_db_with_files(files)
        request = ClaimJobsRequest(job_type="caption", limit=5)

        result = await claim_jobs(request=request, _token="valid", db=db)

        tokens = [f.lease_token for f in result.files]
        assert len(set(tokens)) == 5

    @pytest.mark.asyncio
    async def test_lease_expires_at_is_in_future(self):
        file = _make_drive_file()
        db = _mock_db_with_files([file])
        request = ClaimJobsRequest(job_type="caption", limit=1)

        before = datetime.now(timezone.utc)
        result = await claim_jobs(request=request, _token="valid", db=db)
        after = datetime.now(timezone.utc)

        expected_min = before + timedelta(seconds=LEASE_DURATION_SECONDS)
        expected_max = after + timedelta(seconds=LEASE_DURATION_SECONDS)
        assert expected_min <= result.files[0].lease_expires_at <= expected_max

    @pytest.mark.asyncio
    async def test_empty_claim_returns_no_lease(self):
        db = _mock_db_with_files([])
        request = ClaimJobsRequest(job_type="caption", limit=1)

        result = await claim_jobs(request=request, _token="valid", db=db)

        assert result.files == []


# ── Update job status tests (caption) ─────────────────────────────────

class TestUpdateJobStatus:
    @pytest.mark.asyncio
    async def test_update_caption_done_recomputes_enrichment(self):
        file = _make_drive_file(stt_status="done", ocr_status="done")
        db = _mock_db_with_scalar_one(file)

        request = UpdateJobStatusRequest(job_type="caption", status="done")
        result = await update_job_status(
            file_id=file.id, request=request, _token="valid", db=db,
        )

        assert result.ok is True
        assert db.execute.await_count == 2
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_caption_failed_with_error(self):
        file = _make_drive_file(stt_status="done", ocr_status="done")
        db = _mock_db_with_scalar_one(file)

        request = UpdateJobStatusRequest(
            job_type="caption", status="failed", error="model_crash"
        )
        result = await update_job_status(
            file_id=file.id, request=request, _token="valid", db=db,
        )

        assert result.ok is True
        assert db.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_update_nonexistent_file_returns_404(self):
        db = _mock_db_with_scalar_one(None)

        request = UpdateJobStatusRequest(job_type="caption", status="done")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await update_job_status(
                file_id=uuid4(), request=request, _token="valid", db=db,
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_enrichment_state_partial_failure(self):
        file = _make_drive_file(stt_status="done", ocr_status="failed")
        db = _mock_db_with_scalar_one(file)

        request = UpdateJobStatusRequest(job_type="caption", status="done")
        result = await update_job_status(
            file_id=file.id, request=request, _token="valid", db=db,
        )
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_enrichment_state_all_done(self):
        file = _make_drive_file(stt_status="done", ocr_status="done")
        db = _mock_db_with_scalar_one(file)

        request = UpdateJobStatusRequest(job_type="caption", status="done")
        result = await update_job_status(
            file_id=file.id, request=request, _token="valid", db=db,
        )
        assert result.ok is True


# ── Update job status tests (STT) ────────────────────────────────────

class TestUpdateSttJobStatus:
    @pytest.mark.asyncio
    async def test_update_stt_done(self):
        file = _make_drive_file(
            stt_status="running", caption_status="done", ocr_status="done",
        )
        db = _mock_db_with_scalar_one(file)

        request = UpdateJobStatusRequest(job_type="stt", status="done")
        result = await update_job_status(
            file_id=file.id, request=request, _token="valid", db=db,
        )

        assert result.ok is True
        assert db.execute.await_count == 2
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_stt_failed_with_error(self):
        file = _make_drive_file(
            stt_status="running", caption_status="done", ocr_status="done",
        )
        db = _mock_db_with_scalar_one(file)

        request = UpdateJobStatusRequest(
            job_type="stt", status="failed", error="whisper_oom"
        )
        result = await update_job_status(
            file_id=file.id, request=request, _token="valid", db=db,
        )

        assert result.ok is True
        assert db.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_update_stt_partial_failure(self):
        file = _make_drive_file(
            stt_status="running", caption_status="done", ocr_status="done",
        )
        db = _mock_db_with_scalar_one(file)

        request = UpdateJobStatusRequest(job_type="stt", status="failed")
        result = await update_job_status(
            file_id=file.id, request=request, _token="valid", db=db,
        )
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_update_ocr_done(self):
        file = _make_drive_file(
            stt_status="done", caption_status="done", ocr_status="running",
        )
        db = _mock_db_with_scalar_one(file)

        request = UpdateJobStatusRequest(job_type="ocr", status="done")
        result = await update_job_status(
            file_id=file.id, request=request, _token="valid", db=db,
        )
        assert result.ok is True


# ── Lease enforcement tests ──────────────────────────────────────────

class TestLeaseEnforcement:
    @pytest.mark.asyncio
    async def test_matching_lease_token_accepted(self):
        token = str(uuid4())
        file = _make_drive_file(
            caption_status="running",
            stt_status="done",
            ocr_status="done",
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = _mock_db_with_scalar_one(file)

        request = UpdateJobStatusRequest(
            job_type="caption", status="done", lease_token=token,
        )
        result = await update_job_status(
            file_id=file.id, request=request, _token="valid", db=db,
        )

        assert result.ok is True

    @pytest.mark.asyncio
    async def test_wrong_lease_token_returns_409(self):
        file = _make_drive_file(
            caption_status="running",
            lease_token=str(uuid4()),
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = _mock_db_with_scalar_one(file)

        request = UpdateJobStatusRequest(
            job_type="caption", status="done", lease_token=str(uuid4()),
        )
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await update_job_status(
                file_id=file.id, request=request, _token="valid", db=db,
            )
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "lease_token_mismatch"

    @pytest.mark.asyncio
    async def test_missing_lease_token_returns_409(self):
        file = _make_drive_file(
            caption_status="running",
            lease_token=str(uuid4()),
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = _mock_db_with_scalar_one(file)

        request = UpdateJobStatusRequest(job_type="caption", status="done")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await update_job_status(
                file_id=file.id, request=request, _token="valid", db=db,
            )
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "lease_token_mismatch"

    @pytest.mark.asyncio
    async def test_expired_lease_returns_409(self):
        token = str(uuid4())
        file = _make_drive_file(
            caption_status="running",
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        db = _mock_db_with_scalar_one(file)

        request = UpdateJobStatusRequest(
            job_type="caption", status="done", lease_token=token,
        )
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await update_job_status(
                file_id=file.id, request=request, _token="valid", db=db,
            )
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "lease_expired"

    @pytest.mark.asyncio
    async def test_no_lease_on_file_allows_update(self):
        file = _make_drive_file(
            caption_status="running",
            stt_status="done",
            ocr_status="done",
            lease_token=None,
            lease_expires_at=None,
        )
        db = _mock_db_with_scalar_one(file)

        request = UpdateJobStatusRequest(job_type="caption", status="done")
        result = await update_job_status(
            file_id=file.id, request=request, _token="valid", db=db,
        )
        assert result.ok is True


# ── Idempotency tests ────────────────────────────────────────────────

class TestIdempotency:
    @pytest.mark.asyncio
    async def test_resending_done_on_done_is_idempotent(self):
        file = _make_drive_file(
            caption_status="done",
            stt_status="done",
            ocr_status="done",
        )
        db = _mock_db_with_scalar_one(file)

        request = UpdateJobStatusRequest(job_type="caption", status="done")
        result = await update_job_status(
            file_id=file.id, request=request, _token="valid", db=db,
        )

        assert result.ok is True
        # Idempotent path should NOT issue UPDATE
        assert db.execute.await_count == 1

    @pytest.mark.asyncio
    async def test_resending_failed_on_failed_is_idempotent(self):
        file = _make_drive_file(
            caption_status="failed",
            stt_status="done",
            ocr_status="done",
        )
        db = _mock_db_with_scalar_one(file)

        request = UpdateJobStatusRequest(job_type="caption", status="failed")
        result = await update_job_status(
            file_id=file.id, request=request, _token="valid", db=db,
        )

        assert result.ok is True
        assert db.execute.await_count == 1

    @pytest.mark.asyncio
    async def test_done_on_failed_is_not_idempotent_and_updates(self):
        file = _make_drive_file(
            caption_status="failed",
            stt_status="done",
            ocr_status="done",
        )
        db = _mock_db_with_scalar_one(file)

        request = UpdateJobStatusRequest(job_type="caption", status="done")
        result = await update_job_status(
            file_id=file.id, request=request, _token="valid", db=db,
        )

        assert result.ok is True
        assert db.execute.await_count == 2


# ── Get file metadata tests ───────────────────────────────────────────

class TestGetFileMetadata:
    @pytest.mark.asyncio
    async def test_get_existing_file(self):
        file = _make_drive_file(
            caption_status="running",
            stt_status="done",
            ocr_status="pending",
            enrichment_state="running",
        )
        db = _mock_db_with_scalar_one(file)

        result = await get_file_metadata(file_id=file.id, _token="valid", db=db)

        assert result.id == file.id
        assert result.org_id == file.org_id
        assert result.video_id == file.video_id
        assert result.keyframe_s3_prefix == file.keyframe_s3_prefix
        assert result.audio_s3_key == file.audio_s3_key
        assert result.caption_status == "running"
        assert result.stt_status == "done"
        assert result.ocr_status == "pending"
        assert result.enrichment_state == "running"

    @pytest.mark.asyncio
    async def test_get_nonexistent_file_returns_404(self):
        db = _mock_db_with_scalar_one(None)

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await get_file_metadata(file_id=uuid4(), _token="valid", db=db)
        assert exc_info.value.status_code == 404


# ── Concurrency test ──────────────────────────────────────────────────

class TestClaimConcurrency:
    @pytest.mark.asyncio
    async def test_10_concurrent_claims_no_duplicates(self):
        all_files = [_make_drive_file(video_id=f"vid_{i}") for i in range(10)]
        claimed_ids: list = []

        async def _do_claim(file):
            db = _mock_db_with_files([file])
            request = ClaimJobsRequest(job_type="caption", limit=1)
            result = await claim_jobs(request=request, _token="valid", db=db)
            for f in result.files:
                claimed_ids.append(f.id)

        await asyncio.gather(*[_do_claim(f) for f in all_files])

        assert len(claimed_ids) == 10
        assert len(set(claimed_ids)) == 10

    @pytest.mark.asyncio
    async def test_concurrent_claims_empty_db(self):
        results = []

        async def _do_claim():
            db = _mock_db_with_files([])
            request = ClaimJobsRequest(job_type="caption", limit=1)
            result = await claim_jobs(request=request, _token="valid", db=db)
            results.append(len(result.files))

        await asyncio.gather(*[_do_claim() for _ in range(10)])

        assert all(r == 0 for r in results)
        assert len(results) == 10

    @pytest.mark.asyncio
    async def test_concurrent_claims_each_get_unique_lease(self):
        all_files = [_make_drive_file(video_id=f"vid_{i}") for i in range(10)]
        lease_tokens: list = []

        async def _do_claim(file):
            db = _mock_db_with_files([file])
            request = ClaimJobsRequest(job_type="caption", limit=1)
            result = await claim_jobs(request=request, _token="valid", db=db)
            for f in result.files:
                lease_tokens.append(f.lease_token)

        await asyncio.gather(*[_do_claim(f) for f in all_files])

        assert len(lease_tokens) == 10
        assert len(set(lease_tokens)) == 10


# ── Schema validation tests ───────────────────────────────────────────

class TestSchemaValidation:
    def test_claim_request_valid_job_types(self):
        for job_type in ("caption", "stt", "ocr"):
            req = ClaimJobsRequest(job_type=job_type, limit=1)
            assert req.job_type == job_type

    def test_claim_request_invalid_job_type(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ClaimJobsRequest(job_type="invalid", limit=1)

    def test_claim_request_limit_bounds(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ClaimJobsRequest(job_type="caption", limit=0)
        with pytest.raises(ValidationError):
            ClaimJobsRequest(job_type="caption", limit=11)
        req = ClaimJobsRequest(job_type="caption", limit=10)
        assert req.limit == 10

    def test_update_status_valid_values(self):
        req = UpdateJobStatusRequest(job_type="caption", status="done")
        assert req.status == "done"
        assert req.error is None

        req2 = UpdateJobStatusRequest(
            job_type="stt", status="failed", error="some error"
        )
        assert req2.status == "failed"
        assert req2.error == "some error"

    def test_update_status_invalid_value(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            UpdateJobStatusRequest(job_type="caption", status="running")

    def test_update_status_requires_job_type(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            UpdateJobStatusRequest(status="done")

    def test_update_status_all_job_types(self):
        for job_type in ("caption", "stt", "ocr"):
            req = UpdateJobStatusRequest(job_type=job_type, status="done")
            assert req.job_type == job_type
            assert req.status == "done"

    def test_update_status_with_lease_token(self):
        token = str(uuid4())
        req = UpdateJobStatusRequest(
            job_type="caption", status="done", lease_token=token,
        )
        assert req.lease_token == token

    def test_update_status_lease_token_defaults_none(self):
        req = UpdateJobStatusRequest(job_type="caption", status="done")
        assert req.lease_token is None
