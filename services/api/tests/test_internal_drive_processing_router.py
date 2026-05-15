from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.drive.internal_processing_router import (
    claim_processing,
    update_processing_status,
)
from app.modules.drive.internal_processing_schemas import (
    ClaimProcessingRequest,
    UpdateProcessingStatusRequest,
)


def _make_drive_file(
    *,
    file_id=None,
    org_id=None,
    connection_id=None,
    google_file_id=None,
    file_name="video.mp4",
    video_id="gd_abc123",
    mime_type="video/mp4",
    md5_checksum="abc123",
    file_size_bytes=1024,
    drive_path="/path/video.mp4",
    processing_status="pending",
    is_deleted=False,
    retry_count=0,
    max_retries=3,
    lease_token=None,
    lease_expires_at=None,
    last_error=None,
    last_attempt_at=None,
):
    f = MagicMock()
    f.id = file_id or uuid4()
    f.org_id = org_id or uuid4()
    f.connection_id = connection_id or uuid4()
    f.google_file_id = google_file_id or f"gfile_{uuid4().hex[:8]}"
    f.file_name = file_name
    f.video_id = video_id
    f.mime_type = mime_type
    f.md5_checksum = md5_checksum
    f.file_size_bytes = file_size_bytes
    f.drive_path = drive_path
    f.web_view_link = None
    f.processing_status = processing_status
    f.is_deleted = is_deleted
    f.retry_count = retry_count
    f.max_retries = max_retries
    f.lease_token = lease_token
    f.lease_expires_at = lease_expires_at
    f.last_error = last_error
    f.last_attempt_at = last_attempt_at
    return f


def _make_connection(
    *,
    connection_id=None,
    library_id=None,
    scope_type="drive",
    drive_id="shared-drive-001",
):
    c = MagicMock()
    c.id = connection_id or uuid4()
    c.library_id = library_id or uuid4()
    c.scope_type = scope_type
    c.drive_id = drive_id
    return c


def _mock_db_claim_result(file_connection_pairs):
    db = AsyncMock()
    result = MagicMock()
    result.all.return_value = file_connection_pairs
    db.execute.return_value = result
    db.flush = AsyncMock()
    return db


def _mock_db_select_then_update(entity):
    db = AsyncMock()
    select_result = MagicMock()
    select_result.scalar_one_or_none.return_value = entity
    update_result = MagicMock()
    db.execute = AsyncMock(side_effect=[select_result, update_result])
    db.flush = AsyncMock()
    return db


def _extract_update_values(db):
    stmt = db.execute.await_args_list[1].args[0]
    values = {}
    for key, value in stmt._values.items():
        key_name = getattr(key, "key", str(key))
        values[key_name] = getattr(value, "value", value)
    return values


class TestClaimProcessing:
    @pytest.mark.asyncio
    async def test_claim_single_file(self):
        drive_file = _make_drive_file()
        connection = _make_connection(connection_id=drive_file.connection_id)
        db = _mock_db_claim_result([(drive_file, connection)])

        result = await claim_processing(
            request=ClaimProcessingRequest(limit=1),
            _token="valid",
            db=db,
        )

        assert len(result.files) == 1
        file_info = result.files[0]
        assert file_info.id == drive_file.id
        assert file_info.org_id == drive_file.org_id
        assert file_info.connection_id == drive_file.connection_id
        assert file_info.google_file_id == drive_file.google_file_id
        assert file_info.file_name == "video.mp4"
        assert file_info.video_id == "gd_abc123"
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_claim_empty_returns_empty_list(self):
        db = _mock_db_claim_result([])

        result = await claim_processing(
            request=ClaimProcessingRequest(limit=1),
            _token="valid",
            db=db,
        )

        assert len(result.files) == 0
        db.flush.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_claim_assigns_lease_token(self):
        drive_file = _make_drive_file()
        connection = _make_connection(connection_id=drive_file.connection_id)
        db = _mock_db_claim_result([(drive_file, connection)])

        result = await claim_processing(
            request=ClaimProcessingRequest(limit=1),
            _token="valid",
            db=db,
        )

        assert result.files[0].lease_token is not None
        assert len(result.files[0].lease_token) == 36
        assert drive_file.lease_token == result.files[0].lease_token

    @pytest.mark.asyncio
    async def test_claim_sets_status_to_downloading(self):
        drive_file = _make_drive_file(processing_status="pending")
        connection = _make_connection(connection_id=drive_file.connection_id)
        db = _mock_db_claim_result([(drive_file, connection)])

        await claim_processing(
            request=ClaimProcessingRequest(limit=1),
            _token="valid",
            db=db,
        )

        assert drive_file.processing_status == "downloading"

    @pytest.mark.asyncio
    async def test_claim_returns_connection_fields(self):
        library_id = uuid4()
        drive_file = _make_drive_file()
        connection = _make_connection(
            connection_id=drive_file.connection_id,
            library_id=library_id,
            scope_type="folder",
            drive_id="shared-drive-xyz",
        )
        db = _mock_db_claim_result([(drive_file, connection)])

        result = await claim_processing(
            request=ClaimProcessingRequest(limit=1),
            _token="valid",
            db=db,
        )

        file_info = result.files[0]
        assert file_info.library_id == library_id
        assert file_info.scope_type == "folder"
        assert file_info.drive_id == "shared-drive-xyz"

    @pytest.mark.asyncio
    async def test_claim_multiple_files(self):
        pairs = []
        for i in range(3):
            drive_file = _make_drive_file(video_id=f"gd_{i}")
            connection = _make_connection(connection_id=drive_file.connection_id)
            pairs.append((drive_file, connection))
        db = _mock_db_claim_result(pairs)

        result = await claim_processing(
            request=ClaimProcessingRequest(limit=3),
            _token="valid",
            db=db,
        )

        assert len(result.files) == 3
        assert all(file_obj.processing_status == "downloading" for file_obj, _ in pairs)


class TestUpdateProcessingStatus:
    @pytest.mark.asyncio
    async def test_update_indexed_success(self):
        token = str(uuid4())
        drive_file = _make_drive_file(
            processing_status="processing",
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = _mock_db_select_then_update(drive_file)

        result = await update_processing_status(
            file_id=drive_file.id,
            request=UpdateProcessingStatusRequest(status="indexed", lease_token=token),
            _token="valid",
            db=db,
        )

        assert result.ok is True
        values = _extract_update_values(db)
        assert values["processing_status"] == "indexed"
        assert values["lease_token"] is None
        assert values["lease_expires_at"] is None

    @pytest.mark.asyncio
    async def test_update_failed_with_retry(self):
        token = str(uuid4())
        drive_file = _make_drive_file(
            retry_count=1,
            max_retries=4,
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = _mock_db_select_then_update(drive_file)

        result = await update_processing_status(
            file_id=drive_file.id,
            request=UpdateProcessingStatusRequest(
                status="failed",
                lease_token=token,
                error="network timeout",
            ),
            _token="valid",
            db=db,
        )

        assert result.ok is True
        values = _extract_update_values(db)
        assert values["retry_count"] == 2
        assert values["processing_status"] == "pending"
        assert values["last_error"] == "network timeout"
        assert values["lease_token"] is None
        assert values["lease_expires_at"] is None

    @pytest.mark.asyncio
    async def test_update_failed_max_retries_exhausted(self):
        token = str(uuid4())
        drive_file = _make_drive_file(
            retry_count=2,
            max_retries=3,
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = _mock_db_select_then_update(drive_file)

        result = await update_processing_status(
            file_id=drive_file.id,
            request=UpdateProcessingStatusRequest(
                status="failed",
                lease_token=token,
                error="decode error",
            ),
            _token="valid",
            db=db,
        )

        assert result.ok is True
        values = _extract_update_values(db)
        assert values["retry_count"] == 3
        assert values["processing_status"] == "failed"

    @pytest.mark.asyncio
    async def test_update_intermediate_status(self):
        token = str(uuid4())
        drive_file = _make_drive_file(
            processing_status="downloading",
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = _mock_db_select_then_update(drive_file)

        result = await update_processing_status(
            file_id=drive_file.id,
            request=UpdateProcessingStatusRequest(status="transcoding", lease_token=token),
            _token="valid",
            db=db,
        )

        assert result.ok is True
        values = _extract_update_values(db)
        assert values["processing_status"] == "transcoding"

    @pytest.mark.asyncio
    async def test_update_file_not_found_returns_404(self):
        db = AsyncMock()
        select_result = MagicMock()
        select_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=select_result)

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await update_processing_status(
                file_id=uuid4(),
                request=UpdateProcessingStatusRequest(status="processing"),
                _token="valid",
                db=db,
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_lease_token_mismatch_returns_409(self):
        drive_file = _make_drive_file(
            lease_token=str(uuid4()),
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = AsyncMock()
        select_result = MagicMock()
        select_result.scalar_one_or_none.return_value = drive_file
        db.execute = AsyncMock(return_value=select_result)

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await update_processing_status(
                file_id=drive_file.id,
                request=UpdateProcessingStatusRequest(status="processing", lease_token=str(uuid4())),
                _token="valid",
                db=db,
            )
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "lease_token_mismatch"

    @pytest.mark.asyncio
    async def test_update_lease_expired_returns_409(self):
        token = str(uuid4())
        drive_file = _make_drive_file(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        db = AsyncMock()
        select_result = MagicMock()
        select_result.scalar_one_or_none.return_value = drive_file
        db.execute = AsyncMock(return_value=select_result)

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await update_processing_status(
                file_id=drive_file.id,
                request=UpdateProcessingStatusRequest(status="processing", lease_token=token),
                _token="valid",
                db=db,
            )
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "lease_expired"

    @pytest.mark.asyncio
    async def test_update_idempotent_terminal_status(self):
        drive_file = _make_drive_file(processing_status="indexed", lease_token=str(uuid4()))
        db = AsyncMock()
        select_result = MagicMock()
        select_result.scalar_one_or_none.return_value = drive_file
        db.execute = AsyncMock(return_value=select_result)
        db.flush = AsyncMock()

        result = await update_processing_status(
            file_id=drive_file.id,
            request=UpdateProcessingStatusRequest(status="indexed", lease_token="any"),
            _token="valid",
            db=db,
        )

        assert result.ok is True
        assert db.execute.await_count == 1
        db.flush.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_with_metadata_fields(self):
        token = str(uuid4())
        drive_file = _make_drive_file(
            processing_status="indexing",
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = _mock_db_select_then_update(drive_file)

        result = await update_processing_status(
            file_id=drive_file.id,
            request=UpdateProcessingStatusRequest(
                status="indexed",
                lease_token=token,
                proxy_s3_key="s3://bucket/proxy.mp4",
                proxy_size_bytes=987654,
                proxy_duration_ms=12345,
                thumbnail_s3_prefix="s3://bucket/thumbs/",
                scene_count=12,
                audio_s3_key="s3://bucket/audio.aac",
                keyframe_s3_prefix="s3://bucket/keyframes/",
            ),
            _token="valid",
            db=db,
        )

        assert result.ok is True
        values = _extract_update_values(db)
        assert values["proxy_s3_key"] == "s3://bucket/proxy.mp4"
        assert values["proxy_size_bytes"] == 987654
        assert values["proxy_duration_ms"] == 12345
        assert values["thumbnail_s3_prefix"] == "s3://bucket/thumbs/"
        assert values["scene_count"] == 12
        assert values["audio_s3_key"] == "s3://bucket/audio.aac"
        assert values["keyframe_s3_prefix"] == "s3://bucket/keyframes/"
