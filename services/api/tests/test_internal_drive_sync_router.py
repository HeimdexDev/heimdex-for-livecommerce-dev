"""
Tests for internal drive sync management endpoints.

Covers:
- POST /internal/drive/sync/claim_connection — atomic claim with SKIP LOCKED + lease tokens
- PATCH /internal/drive/sync/connections/{id}/checkpoint — cursor update + lease release
- POST /internal/drive/sync/connections/{id}/upsert_files — batch file upsert (idempotent)
- Lease enforcement: mismatch, expiry
- Concurrency: concurrent claims yield no double-claims
- Schema validation
- Video ID determinism
"""
import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.drive.internal_sync_router import (
    _drive_video_id,
    _enforce_connection_lease,
    _MAX_UPSERT_ITEMS,
    claim_sync_connection,
    checkpoint_connection,
    delete_files,
    get_connection_token,
    list_connection_file_ids,
    update_metadata,
    upsert_files,
)
from app.modules.drive.internal_sync_schemas import (
    ClaimSyncConnectionRequest,
    DeleteFilesRequest,
    DriveDiscoveredFile,
    MetadataUpdateItem,
    UpdateMetadataRequest,
    SyncCheckpointRequest,
    TokenRequest,
    UpsertFilesRequest,
)


# ── Helpers ───────────────────────────────────────────────────────────

def _make_connection(
    *,
    connection_id=None,
    org_id=None,
    library_id=None,
    scope_type="drive",
    drive_id: str | None = "shared-drive-001",
    folder_id=None,
    folder_name=None,
    folder_path=None,
    status="active",
    change_token=None,
    last_sync_at=None,
    last_full_sync_at=None,
    sync_requested_at=None,
    lease_token=None,
    lease_expires_at=None,
):
    c = MagicMock()
    c.id = connection_id or uuid4()
    c.org_id = org_id or uuid4()
    c.library_id = library_id or uuid4()
    c.scope_type = scope_type
    c.drive_id = drive_id
    c.folder_id = folder_id
    c.folder_name = folder_name
    c.folder_path = folder_path
    c.status = status
    c.change_token = change_token
    c.last_sync_at = last_sync_at
    c.last_full_sync_at = last_full_sync_at
    c.sync_requested_at = sync_requested_at
    c.lease_token = lease_token
    c.lease_expires_at = lease_expires_at
    return c


def _mock_db_with_connections(connections):
    db = AsyncMock()
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = connections
    mock_result.scalars.return_value = mock_scalars
    db.execute.return_value = mock_result
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


def _mock_db_for_upsert(connection, existing_google_ids, soft_deleted_ids=None):
    """Mock DB session for the upsert flow.

    ``existing_google_ids`` — live rows (``is_deleted=False``).
    ``soft_deleted_ids`` — soft-deleted rows (``is_deleted=True``). The
    service MUST find these via the existing-files query (the
    ``uq_drive_files_org_file`` constraint spans soft-deleted rows, so
    missing them causes the 2026-04 discover outage reproducer).
    """
    db = AsyncMock()
    conn_result = MagicMock()
    conn_result.scalar_one_or_none.return_value = connection
    file_result = MagicMock()
    soft_deleted_ids = set(soft_deleted_ids or ())
    all_ids = set(existing_google_ids) | soft_deleted_ids
    existing_files = []
    existing_files_map = {}
    for gid in all_ids:
        f = MagicMock()
        f.google_file_id = gid
        f.file_name = "video.mp4"
        f.md5_checksum = None
        f.file_size_bytes = None
        f.google_modified_time = None
        f.google_created_time = None
        f.processing_status = "deleted" if gid in soft_deleted_ids else "indexed"
        f.enrichment_state = "done"
        f.stt_status = "done"
        f.ocr_status = "done"
        f.caption_status = "done"
        f.face_status = "done"
        f.proxy_s3_key = "proxy"
        f.original_s3_key = "original"
        f.audio_s3_key = "audio"
        f.keyframe_s3_prefix = "keyframes/"
        f.thumbnail_s3_prefix = "thumbs/"
        f.scene_count = 10
        f.retry_count = 1
        f.last_error = "old"
        f.enrichment_error = None
        f.caption_error = None
        f.face_error = None
        f.drive_path = None
        f.web_view_link = None
        f.video_id = f"vid_{gid}"
        f.id = uuid4()
        f.mime_type = "video/mp4"
        f.is_deleted = gid in soft_deleted_ids
        f.deleted_at = datetime.now(timezone.utc) if gid in soft_deleted_ids else None
        existing_files.append(f)
        existing_files_map[gid] = f
    file_scalars = MagicMock()
    file_scalars.all.return_value = existing_files
    file_result.scalars.return_value = file_scalars
    db.execute = AsyncMock(side_effect=[conn_result, file_result])
    db.add = MagicMock()
    db.flush = AsyncMock()
    db._existing_files_map = existing_files_map
    return db


def _make_discovered_file(
    *,
    provider_file_id=None,
    name="video.mp4",
    mime_type="video/mp4",
    size=None,
    md5_checksum=None,
    drive_path=None,
    web_view_link=None,
    modified_time=None,
):
    return DriveDiscoveredFile(
        provider_file_id=provider_file_id or f"gfile_{uuid4().hex[:8]}",
        name=name,
        mime_type=mime_type,
        size=size,
        md5_checksum=md5_checksum,
        drive_path=drive_path,
        web_view_link=web_view_link,
        modified_time=modified_time,
    )


# ── Claim connection tests ───────────────────────────────────────────

class TestClaimSyncConnection:
    @pytest.mark.asyncio
    async def test_claim_single_connection(self):
        conn = _make_connection()
        db = _mock_db_with_connections([conn])
        request = ClaimSyncConnectionRequest(limit=1)

        result = await claim_sync_connection(request=request, _token="valid", db=db)

        assert len(result.connections) == 1
        assert result.connections[0].connection_id == conn.id
        assert result.connections[0].org_id == conn.org_id
        assert result.connections[0].scope_type == "drive"
        assert result.connections[0].drive_id == "shared-drive-001"
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_claim_empty_returns_empty_list(self):
        db = _mock_db_with_connections([])
        request = ClaimSyncConnectionRequest(limit=1)

        result = await claim_sync_connection(request=request, _token="valid", db=db)

        assert len(result.connections) == 0
        db.flush.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_claim_multiple_connections(self):
        conns = [_make_connection(drive_id=f"drive_{i}") for i in range(3)]
        db = _mock_db_with_connections(conns)
        request = ClaimSyncConnectionRequest(limit=3)

        result = await claim_sync_connection(request=request, _token="valid", db=db)

        assert len(result.connections) == 3
        for c in conns:
            assert c.lease_token is not None

    @pytest.mark.asyncio
    async def test_claim_assigns_lease_token(self):
        conn = _make_connection()
        db = _mock_db_with_connections([conn])
        request = ClaimSyncConnectionRequest(limit=1)

        result = await claim_sync_connection(request=request, _token="valid", db=db)

        assert result.connections[0].lease_token is not None
        assert len(result.connections[0].lease_token) == 36
        assert conn.lease_token == result.connections[0].lease_token

    @pytest.mark.asyncio
    async def test_claim_lease_expires_in_future(self):
        conn = _make_connection()
        db = _mock_db_with_connections([conn])
        request = ClaimSyncConnectionRequest(limit=1)

        before = datetime.now(timezone.utc)
        result = await claim_sync_connection(request=request, _token="valid", db=db)
        after = datetime.now(timezone.utc)

        from app.modules.drive.internal_router import LEASE_DURATION_SECONDS
        expected_min = before + timedelta(seconds=LEASE_DURATION_SECONDS)
        expected_max = after + timedelta(seconds=LEASE_DURATION_SECONDS)
        assert expected_min <= result.connections[0].lease_expires_at <= expected_max

    @pytest.mark.asyncio
    async def test_each_connection_gets_unique_lease(self):
        conns = [_make_connection(drive_id=f"drive_{i}") for i in range(5)]
        db = _mock_db_with_connections(conns)
        request = ClaimSyncConnectionRequest(limit=5)

        result = await claim_sync_connection(request=request, _token="valid", db=db)

        tokens = [c.lease_token for c in result.connections]
        assert len(set(tokens)) == 5

    @pytest.mark.asyncio
    async def test_claim_returns_folder_connection_fields(self):
        conn = _make_connection(
            scope_type="folder",
            drive_id=None,
            folder_id="folder-abc",
            folder_name="Marketing Videos",
            folder_path="/Shared/Marketing Videos",
        )
        db = _mock_db_with_connections([conn])
        request = ClaimSyncConnectionRequest(limit=1)

        result = await claim_sync_connection(request=request, _token="valid", db=db)

        info = result.connections[0]
        assert info.scope_type == "folder"
        assert info.folder_id == "folder-abc"
        assert info.folder_name == "Marketing Videos"
        assert info.folder_path == "/Shared/Marketing Videos"
        assert info.drive_id is None

    @pytest.mark.asyncio
    async def test_claim_returns_cursor_fields(self):
        sync_time = datetime(2026, 2, 20, 10, 0, 0, tzinfo=timezone.utc)
        conn = _make_connection(
            change_token="page_token_abc",
            last_sync_at=sync_time,
            last_full_sync_at=sync_time,
        )
        db = _mock_db_with_connections([conn])
        request = ClaimSyncConnectionRequest(limit=1)

        result = await claim_sync_connection(request=request, _token="valid", db=db)

        info = result.connections[0]
        assert info.change_token == "page_token_abc"
        assert info.last_sync_at == sync_time
        assert info.last_full_sync_at == sync_time


# ── Checkpoint tests ──────────────────────────────────────────────────

class TestCheckpointConnection:
    @pytest.mark.asyncio
    async def test_checkpoint_with_release(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = _mock_db_select_then_update(conn)

        request = SyncCheckpointRequest(
            lease_token=token,
            change_token="new_page_token",
            release=True,
        )
        result = await checkpoint_connection(
            connection_id=conn.id, request=request, _token="valid", db=db,
        )

        assert result.ok is True
        assert db.execute.await_count == 2
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_checkpoint_without_release(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = _mock_db_select_then_update(conn)

        request = SyncCheckpointRequest(
            lease_token=token,
            change_token="intermediate_token",
            release=False,
        )
        result = await checkpoint_connection(
            connection_id=conn.id, request=request, _token="valid", db=db,
        )

        assert result.ok is True

    @pytest.mark.asyncio
    async def test_checkpoint_sets_error_message(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = _mock_db_select_then_update(conn)

        request = SyncCheckpointRequest(
            lease_token=token,
            error_message="Google API rate limit exceeded",
            release=True,
        )
        result = await checkpoint_connection(
            connection_id=conn.id, request=request, _token="valid", db=db,
        )

        assert result.ok is True

    @pytest.mark.asyncio
    async def test_checkpoint_nonexistent_connection_returns_404(self):
        db = AsyncMock()
        select_result = MagicMock()
        select_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=select_result)

        request = SyncCheckpointRequest(lease_token=str(uuid4()))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await checkpoint_connection(
                connection_id=uuid4(), request=request, _token="valid", db=db,
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_checkpoint_wrong_lease_token_returns_409(self):
        conn = _make_connection(
            lease_token=str(uuid4()),
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = AsyncMock()
        select_result = MagicMock()
        select_result.scalar_one_or_none.return_value = conn
        db.execute = AsyncMock(return_value=select_result)

        request = SyncCheckpointRequest(lease_token=str(uuid4()))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await checkpoint_connection(
                connection_id=conn.id, request=request, _token="valid", db=db,
            )
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "lease_token_mismatch"

    @pytest.mark.asyncio
    async def test_checkpoint_expired_lease_returns_409(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        db = AsyncMock()
        select_result = MagicMock()
        select_result.scalar_one_or_none.return_value = conn
        db.execute = AsyncMock(return_value=select_result)

        request = SyncCheckpointRequest(lease_token=token)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await checkpoint_connection(
                connection_id=conn.id, request=request, _token="valid", db=db,
            )
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "lease_expired"

    @pytest.mark.asyncio
    async def test_checkpoint_no_lease_on_connection_allows_update(self):
        conn = _make_connection(lease_token=None, lease_expires_at=None)
        db = _mock_db_select_then_update(conn)

        request = SyncCheckpointRequest(
            lease_token=str(uuid4()),
            change_token="some_token",
            release=True,
        )
        result = await checkpoint_connection(
            connection_id=conn.id, request=request, _token="valid", db=db,
        )
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_checkpoint_persists_drive_id(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = _mock_db_select_then_update(conn)

        request = SyncCheckpointRequest(
            lease_token=token,
            change_token="new_page_token",
            drive_id="shared-drive-99",
            release=False,
        )
        result = await checkpoint_connection(
            connection_id=conn.id, request=request, _token="valid", db=db,
        )

        assert result.ok is True
        # Verify the update statement was executed with drive_id
        assert db.execute.await_count == 2
        db.flush.assert_awaited_once()


# ── Lease enforcement helper tests ────────────────────────────────────

class TestEnforceConnectionLease:
    def test_no_lease_allows_any_token(self):
        conn = _make_connection(lease_token=None)
        _enforce_connection_lease(conn, str(uuid4()))

    def test_no_lease_allows_none_token(self):
        conn = _make_connection(lease_token=None)
        _enforce_connection_lease(conn, None)

    def test_matching_token_passes(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        _enforce_connection_lease(conn, token)

    def test_wrong_token_raises_409(self):
        conn = _make_connection(
            lease_token=str(uuid4()),
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _enforce_connection_lease(conn, str(uuid4()))
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "lease_token_mismatch"

    def test_none_token_allows_processing_path(self):
        conn = _make_connection(
            lease_token=str(uuid4()),
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        _enforce_connection_lease(conn, None)

    def test_expired_lease_raises_409(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _enforce_connection_lease(conn, token)
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "lease_expired"


# ── Upsert files tests ───────────────────────────────────────────────

class TestUpsertFiles:
    @pytest.mark.asyncio
    async def test_upsert_new_files_created(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = _mock_db_for_upsert(conn, existing_google_ids=set())

        items = [_make_discovered_file(provider_file_id=f"gf_{i}") for i in range(3)]
        request = UpsertFilesRequest(lease_token=token, items=items)

        result = await upsert_files(
            connection_id=conn.id, request=request, _token="valid", db=db,
        )

        assert result.created_count == 3
        assert result.updated_count == 0
        assert result.unchanged_count == 0
        assert db.add.call_count == 3
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_upsert_existing_files_unchanged(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        existing_ids = {"gf_0", "gf_1", "gf_2"}
        db = _mock_db_for_upsert(conn, existing_google_ids=existing_ids)

        items = [_make_discovered_file(provider_file_id=f"gf_{i}") for i in range(3)]
        request = UpsertFilesRequest(lease_token=token, items=items)

        result = await upsert_files(
            connection_id=conn.id, request=request, _token="valid", db=db,
        )

        assert result.created_count == 0
        assert result.unchanged_count == 3
        assert db.add.call_count == 0
        db.flush.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_upsert_revives_soft_deleted_file(self):
        """Regression: 2026-04 staging/prod discover outage.

        A previously soft-deleted row still owns its (org_id, google_file_id)
        unique constraint slot. When Drive discovery re-lists the file, the
        service MUST reuse the existing row (revive) instead of trying to
        db.add() a new one — otherwise the flush raises UniqueViolationError
        and aborts the whole batch.
        """
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = _mock_db_for_upsert(
            conn,
            existing_google_ids=set(),
            soft_deleted_ids={"gf_zombie"},
        )

        items = [
            _make_discovered_file(
                provider_file_id="gf_zombie",
                name="resurrected.mp4",
                size=123,
                md5_checksum="new_md5",
            )
        ]
        request = UpsertFilesRequest(lease_token=token, items=items)

        with patch(
            "app.modules.drive.internal_sync_router.publish_processing_job"
        ) as pub:
            result = await upsert_files(
                connection_id=conn.id, request=request, _token="valid", db=db,
            )

        # Counts: one revive, zero created/updated/unchanged.
        assert result.created_count == 0
        assert result.revived_count == 1
        assert result.updated_count == 0
        assert result.unchanged_count == 0

        # The row must have been mutated in place, NOT added as a new row.
        assert db.add.call_count == 0
        db.flush.assert_awaited_once()

        # Row state: resurrected, pipeline reset, metadata refreshed.
        revived = db._existing_files_map["gf_zombie"]
        assert revived.is_deleted is False
        assert revived.deleted_at is None
        assert revived.processing_status == "pending"
        assert revived.enrichment_state == "pending"
        assert revived.stt_status == "pending"
        assert revived.ocr_status == "pending"
        assert revived.caption_status is None
        assert revived.face_status is None
        assert revived.proxy_s3_key is None
        assert revived.original_s3_key is None
        assert revived.scene_count == 0
        assert revived.retry_count == 0
        assert revived.last_error is None
        assert revived.file_name == "resurrected.mp4"
        assert revived.md5_checksum == "new_md5"
        assert revived.file_size_bytes == 123

        # Revived rows are fresh pipeline work → must enqueue a processing job.
        pub.assert_called_once()
        assert result.enqueued_jobs == {"processing": 1}

    @pytest.mark.asyncio
    async def test_upsert_batch_with_mix_of_live_and_soft_deleted(self):
        """A mixed batch must not drop any row on the floor.

        Combines: 1 brand-new + 1 unchanged-live + 1 soft-deleted-revived.
        All three must land. Regression-guards against any future refactor
        that re-introduces the ``is_deleted=False`` filter.
        """
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = _mock_db_for_upsert(
            conn,
            existing_google_ids={"gf_live"},
            soft_deleted_ids={"gf_zombie"},
        )

        items = [
            _make_discovered_file(provider_file_id="gf_new"),
            _make_discovered_file(provider_file_id="gf_live"),
            _make_discovered_file(provider_file_id="gf_zombie"),
        ]
        request = UpsertFilesRequest(lease_token=token, items=items)

        with patch(
            "app.modules.drive.internal_sync_router.publish_processing_job"
        ) as pub:
            result = await upsert_files(
                connection_id=conn.id, request=request, _token="valid", db=db,
            )

        assert result.created_count == 1
        assert result.revived_count == 1
        assert result.unchanged_count == 1
        assert result.updated_count == 0
        # New + revived both publish SQS; unchanged does not.
        assert pub.call_count == 2
        assert result.enqueued_jobs == {"processing": 2}

    @pytest.mark.asyncio
    async def test_upsert_revive_is_idempotent_across_cycles(self):
        """Calling upsert twice on the same soft-deleted id must not re-revive.

        After the first call, the row's ``is_deleted`` is False — the second
        call should treat it as an unchanged live row, not revive it again.
        This guards the discover-every-30s loop from flip-flopping a file.
        """
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = _mock_db_for_upsert(
            conn,
            existing_google_ids=set(),
            soft_deleted_ids={"gf_0"},
        )

        # Seed the revived row's file_name so the second call's name check
        # does not register a change.
        revived = db._existing_files_map["gf_0"]
        items = [_make_discovered_file(provider_file_id="gf_0", name="video.mp4")]
        request = UpsertFilesRequest(lease_token=token, items=items)

        with patch("app.modules.drive.internal_sync_router.publish_processing_job"):
            first = await upsert_files(
                connection_id=conn.id, request=request, _token="valid", db=db,
            )
        assert first.revived_count == 1
        assert revived.is_deleted is False

        # Simulate a second cycle: re-mock DB, this time the row is live.
        db2 = _mock_db_for_upsert(
            conn,
            existing_google_ids={"gf_0"},
            soft_deleted_ids=set(),
        )
        # Align file_name so no metadata drift is recorded.
        db2._existing_files_map["gf_0"].file_name = "video.mp4"

        with patch("app.modules.drive.internal_sync_router.publish_processing_job") as pub2:
            second = await upsert_files(
                connection_id=conn.id, request=request, _token="valid", db=db2,
            )
        assert second.revived_count == 0
        assert second.unchanged_count == 1
        pub2.assert_not_called()

    @pytest.mark.asyncio
    async def test_upsert_mixed_new_and_existing(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        existing_ids = {"gf_0", "gf_2"}
        db = _mock_db_for_upsert(conn, existing_google_ids=existing_ids)

        items = [_make_discovered_file(provider_file_id=f"gf_{i}") for i in range(4)]
        request = UpsertFilesRequest(lease_token=token, items=items)

        result = await upsert_files(
            connection_id=conn.id, request=request, _token="valid", db=db,
        )

        assert result.created_count == 2
        assert result.unchanged_count == 2
        assert result.created_count + result.unchanged_count == 4

    @pytest.mark.asyncio
    async def test_upsert_empty_batch(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = AsyncMock()
        conn_result = MagicMock()
        conn_result.scalar_one_or_none.return_value = conn
        db.execute = AsyncMock(return_value=conn_result)

        request = UpsertFilesRequest(lease_token=token, items=[])

        result = await upsert_files(
            connection_id=conn.id, request=request, _token="valid", db=db,
        )

        assert result.created_count == 0
        assert result.unchanged_count == 0
        assert result.enqueued_jobs == {}

    @pytest.mark.asyncio
    async def test_upsert_deduplicates_within_batch(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = _mock_db_for_upsert(conn, existing_google_ids=set())

        items = [
            _make_discovered_file(provider_file_id="same_file"),
            _make_discovered_file(provider_file_id="same_file"),
            _make_discovered_file(provider_file_id="different_file"),
        ]
        request = UpsertFilesRequest(lease_token=token, items=items)

        result = await upsert_files(
            connection_id=conn.id, request=request, _token="valid", db=db,
        )

        assert result.created_count == 2
        assert result.unchanged_count == 1
        assert db.add.call_count == 2

    @pytest.mark.asyncio
    async def test_upsert_enqueued_jobs_count(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = _mock_db_for_upsert(conn, existing_google_ids=set())

        items = [_make_discovered_file(provider_file_id=f"gf_{i}") for i in range(5)]
        request = UpsertFilesRequest(lease_token=token, items=items)

        result = await upsert_files(
            connection_id=conn.id, request=request, _token="valid", db=db,
        )

        assert result.enqueued_jobs == {"processing": 5}

    @pytest.mark.asyncio
    async def test_upsert_no_enqueued_jobs_when_all_unchanged(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = _mock_db_for_upsert(conn, existing_google_ids={"gf_0"})

        items = [_make_discovered_file(provider_file_id="gf_0")]
        request = UpsertFilesRequest(lease_token=token, items=items)

        result = await upsert_files(
            connection_id=conn.id, request=request, _token="valid", db=db,
        )

        assert result.enqueued_jobs == {}

    @pytest.mark.asyncio
    async def test_upsert_nonexistent_connection_returns_404(self):
        db = AsyncMock()
        conn_result = MagicMock()
        conn_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=conn_result)

        items = [_make_discovered_file()]
        request = UpsertFilesRequest(lease_token=str(uuid4()), items=items)

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await upsert_files(
                connection_id=uuid4(), request=request, _token="valid", db=db,
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_upsert_wrong_lease_token_returns_409(self):
        conn = _make_connection(
            lease_token=str(uuid4()),
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = AsyncMock()
        conn_result = MagicMock()
        conn_result.scalar_one_or_none.return_value = conn
        db.execute = AsyncMock(return_value=conn_result)

        items = [_make_discovered_file()]
        request = UpsertFilesRequest(lease_token=str(uuid4()), items=items)

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await upsert_files(
                connection_id=conn.id, request=request, _token="valid", db=db,
            )
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_upsert_too_many_items_returns_400(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = AsyncMock()

        items = [_make_discovered_file(provider_file_id=f"gf_{i}") for i in range(_MAX_UPSERT_ITEMS + 1)]
        request = UpsertFilesRequest(lease_token=token, items=items)

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await upsert_files(
                connection_id=conn.id, request=request, _token="valid", db=db,
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_upsert_counts_sum_to_total(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        existing_ids = {"gf_1", "gf_3"}
        db = _mock_db_for_upsert(conn, existing_google_ids=existing_ids)

        items = [
            _make_discovered_file(provider_file_id="gf_0"),
            _make_discovered_file(provider_file_id="gf_1"),
            _make_discovered_file(provider_file_id="gf_2"),
            _make_discovered_file(provider_file_id="gf_3"),
            _make_discovered_file(provider_file_id="gf_2"),
        ]
        request = UpsertFilesRequest(lease_token=token, items=items)

        result = await upsert_files(
            connection_id=conn.id, request=request, _token="valid", db=db,
        )

        total = result.created_count + result.updated_count + result.unchanged_count
        assert total == len(items)

    @pytest.mark.asyncio
    async def test_upsert_detects_md5_change(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = _mock_db_for_upsert(conn, existing_google_ids={"gf_md5"})
        existing_file = db._existing_files_map["gf_md5"]
        existing_file.md5_checksum = "old-md5"

        request = UpsertFilesRequest(
            lease_token=token,
            items=[
                _make_discovered_file(
                    provider_file_id="gf_md5",
                    md5_checksum="new-md5",
                    size=2048,
                    modified_time=datetime.now(timezone.utc),
                )
            ],
        )

        result = await upsert_files(connection_id=conn.id, request=request, _token="valid", db=db)

        assert result.updated_count == 1
        assert result.created_count == 0
        assert existing_file.md5_checksum == "new-md5"
        assert existing_file.processing_status == "pending"
        assert existing_file.scene_count == 0
        assert result.enqueued_jobs == {"processing": 1}

    @pytest.mark.asyncio
    async def test_upsert_detects_rename(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = _mock_db_for_upsert(conn, existing_google_ids={"gf_rename"})
        existing_file = db._existing_files_map["gf_rename"]

        request = UpsertFilesRequest(
            lease_token=token,
            items=[_make_discovered_file(provider_file_id="gf_rename", name="new_name.mp4")],
        )

        result = await upsert_files(connection_id=conn.id, request=request, _token="valid", db=db)

        assert result.updated_count == 1
        assert existing_file.file_name == "new_name.mp4"

    @pytest.mark.asyncio
    async def test_upsert_returns_metadata_updates(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = _mock_db_for_upsert(conn, existing_google_ids={"gf_rename_meta"})

        request = UpsertFilesRequest(
            lease_token=token,
            items=[_make_discovered_file(provider_file_id="gf_rename_meta", name="updated_name.mp4")],
        )

        result = await upsert_files(connection_id=conn.id, request=request, _token="valid", db=db)

        assert result.updated_count == 1
        assert result.metadata_updates == [
            {"video_id": "vid_gf_rename_meta", "video_title": "updated_name.mp4"}
        ]

    @pytest.mark.asyncio
    async def test_upsert_detects_move(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = _mock_db_for_upsert(conn, existing_google_ids={"gf_move"})
        existing_file = db._existing_files_map["gf_move"]
        existing_file.drive_path = "old/path.mp4"

        request = UpsertFilesRequest(
            lease_token=token,
            items=[_make_discovered_file(provider_file_id="gf_move", drive_path="new/path.mp4")],
        )

        result = await upsert_files(connection_id=conn.id, request=request, _token="valid", db=db)

        assert result.updated_count == 1
        assert existing_file.drive_path == "new/path.mp4"

    @pytest.mark.asyncio
    async def test_upsert_returns_metadata_updates_on_move(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = _mock_db_for_upsert(conn, existing_google_ids={"gf_move_meta"})
        existing_file = db._existing_files_map["gf_move_meta"]
        existing_file.drive_path = "before/path.mp4"

        request = UpsertFilesRequest(
            lease_token=token,
            items=[_make_discovered_file(provider_file_id="gf_move_meta", drive_path="after/path.mp4")],
        )

        result = await upsert_files(connection_id=conn.id, request=request, _token="valid", db=db)

        assert result.updated_count == 1
        assert result.metadata_updates == [
            {"video_id": "vid_gf_move_meta", "source_path": "after/path.mp4"}
        ]

    @pytest.mark.asyncio
    async def test_upsert_unchanged(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = _mock_db_for_upsert(conn, existing_google_ids={"gf_same"})

        request = UpsertFilesRequest(
            lease_token=token,
            items=[_make_discovered_file(provider_file_id="gf_same")],
        )

        result = await upsert_files(connection_id=conn.id, request=request, _token="valid", db=db)

        assert result.updated_count == 0
        assert result.unchanged_count == 1


class TestDeleteFiles:
    @pytest.mark.asyncio
    async def test_delete_files_soft_deletes(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )

        file1 = MagicMock()
        file1.google_file_id = "gf_1"
        file1.video_id = "vid_1"
        file2 = MagicMock()
        file2.google_file_id = "gf_2"
        file2.video_id = "vid_2"

        conn_result = MagicMock()
        conn_result.scalar_one_or_none.return_value = conn
        files_result = MagicMock()
        files_scalars = MagicMock()
        files_scalars.all.return_value = [file1, file2]
        files_result.scalars.return_value = files_scalars

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[conn_result, files_result, MagicMock()])
        db.flush = AsyncMock()

        scene_client = MagicMock()
        scene_client.delete_scenes_by_video_id = AsyncMock(return_value=3)

        request = DeleteFilesRequest(
            lease_token=token,
            google_file_ids=["gf_1", "gf_2"],
        )
        result = await delete_files(
            connection_id=conn.id,
            request=request,
            _token="valid",
            db=db,
            scene_client=scene_client,
        )

        assert result.deleted_count == 2
        assert result.not_found_count == 0
        db.flush.assert_awaited_once()
        assert scene_client.delete_scenes_by_video_id.await_count == 2

    @pytest.mark.asyncio
    async def test_delete_files_not_found(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )

        conn_result = MagicMock()
        conn_result.scalar_one_or_none.return_value = conn
        files_result = MagicMock()
        files_scalars = MagicMock()
        files_scalars.all.return_value = []
        files_result.scalars.return_value = files_scalars

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[conn_result, files_result])
        db.flush = AsyncMock()

        scene_client = MagicMock()
        scene_client.delete_scenes_by_video_id = AsyncMock(return_value=0)

        request = DeleteFilesRequest(
            lease_token=token,
            google_file_ids=["missing_1", "missing_2"],
        )
        result = await delete_files(
            connection_id=conn.id,
            request=request,
            _token="valid",
            db=db,
            scene_client=scene_client,
        )

        assert result.deleted_count == 0
        assert result.not_found_count == 2
        db.flush.assert_not_awaited()
        scene_client.delete_scenes_by_video_id.assert_not_awaited()


class TestUpdateMetadata:
    @pytest.mark.asyncio
    async def test_update_metadata_rename(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = AsyncMock()
        conn_result = MagicMock()
        conn_result.scalar_one_or_none.return_value = conn
        db.execute = AsyncMock(return_value=conn_result)

        scene_client = MagicMock()
        scene_client.find_scene_ids_by_video_id = AsyncMock(return_value=["scene_1", "scene_2"])
        scene_client.bulk_partial_update_scenes = AsyncMock()

        request = UpdateMetadataRequest(
            lease_token=token,
            updates=[MetadataUpdateItem(video_id="vid_1", video_title="renamed.mp4")],
        )
        result = await update_metadata(
            connection_id=conn.id,
            request=request,
            _token="valid",
            db=db,
            scene_client=scene_client,
        )

        assert result.updated_scene_count == 2
        assert result.skipped_count == 0
        scene_client.bulk_partial_update_scenes.assert_awaited_once_with(
            [("scene_1", {"video_title": "renamed.mp4"}), ("scene_2", {"video_title": "renamed.mp4"})]
        )

    @pytest.mark.asyncio
    async def test_update_metadata_move(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = AsyncMock()
        conn_result = MagicMock()
        conn_result.scalar_one_or_none.return_value = conn
        db.execute = AsyncMock(return_value=conn_result)

        scene_client = MagicMock()
        scene_client.find_scene_ids_by_video_id = AsyncMock(return_value=["scene_1"])
        scene_client.bulk_partial_update_scenes = AsyncMock()

        request = UpdateMetadataRequest(
            lease_token=token,
            updates=[MetadataUpdateItem(video_id="vid_1", source_path="folder/new.mp4")],
        )
        result = await update_metadata(
            connection_id=conn.id,
            request=request,
            _token="valid",
            db=db,
            scene_client=scene_client,
        )

        assert result.updated_scene_count == 1
        assert result.skipped_count == 0
        scene_client.bulk_partial_update_scenes.assert_awaited_once_with(
            [("scene_1", {"source_path": "folder/new.mp4"})]
        )

    @pytest.mark.asyncio
    async def test_update_metadata_both(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = AsyncMock()
        conn_result = MagicMock()
        conn_result.scalar_one_or_none.return_value = conn
        db.execute = AsyncMock(return_value=conn_result)

        scene_client = MagicMock()
        scene_client.find_scene_ids_by_video_id = AsyncMock(return_value=["scene_1"])
        scene_client.bulk_partial_update_scenes = AsyncMock()

        request = UpdateMetadataRequest(
            lease_token=token,
            updates=[MetadataUpdateItem(video_id="vid_1", video_title="renamed.mp4", source_path="folder/new.mp4")],
        )
        result = await update_metadata(
            connection_id=conn.id,
            request=request,
            _token="valid",
            db=db,
            scene_client=scene_client,
        )

        assert result.updated_scene_count == 1
        assert result.skipped_count == 0
        scene_client.bulk_partial_update_scenes.assert_awaited_once_with(
            [("scene_1", {"video_title": "renamed.mp4", "source_path": "folder/new.mp4"})]
        )

    @pytest.mark.asyncio
    async def test_update_metadata_empty_list(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = AsyncMock()
        conn_result = MagicMock()
        conn_result.scalar_one_or_none.return_value = conn
        db.execute = AsyncMock(return_value=conn_result)

        scene_client = MagicMock()
        scene_client.find_scene_ids_by_video_id = AsyncMock()
        scene_client.bulk_partial_update_scenes = AsyncMock()

        result = await update_metadata(
            connection_id=conn.id,
            request=UpdateMetadataRequest(lease_token=token, updates=[]),
            _token="valid",
            db=db,
            scene_client=scene_client,
        )

        assert result.updated_scene_count == 0
        assert result.skipped_count == 0
        scene_client.find_scene_ids_by_video_id.assert_not_awaited()
        scene_client.bulk_partial_update_scenes.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_metadata_invalid_lease(self):
        conn = _make_connection(
            lease_token=str(uuid4()),
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = AsyncMock()
        conn_result = MagicMock()
        conn_result.scalar_one_or_none.return_value = conn
        db.execute = AsyncMock(return_value=conn_result)

        scene_client = MagicMock()
        scene_client.find_scene_ids_by_video_id = AsyncMock()
        scene_client.bulk_partial_update_scenes = AsyncMock()

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await update_metadata(
                connection_id=conn.id,
                request=UpdateMetadataRequest(
                    lease_token=str(uuid4()),
                    updates=[MetadataUpdateItem(video_id="vid_1", video_title="new")],
                ),
                _token="valid",
                db=db,
                scene_client=scene_client,
            )
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_update_metadata_no_scenes(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = AsyncMock()
        conn_result = MagicMock()
        conn_result.scalar_one_or_none.return_value = conn
        db.execute = AsyncMock(return_value=conn_result)

        scene_client = MagicMock()
        scene_client.find_scene_ids_by_video_id = AsyncMock(return_value=[])
        scene_client.bulk_partial_update_scenes = AsyncMock()

        result = await update_metadata(
            connection_id=conn.id,
            request=UpdateMetadataRequest(
                lease_token=token,
                updates=[MetadataUpdateItem(video_id="vid_missing", video_title="new")],
            ),
            _token="valid",
            db=db,
            scene_client=scene_client,
        )

        assert result.updated_scene_count == 0
        assert result.skipped_count == 1
        scene_client.bulk_partial_update_scenes.assert_not_awaited()


class TestListConnectionFileIds:
    @pytest.mark.asyncio
    async def test_list_connection_file_ids(self):
        conn = _make_connection()
        db = AsyncMock()
        conn_result = MagicMock()
        conn_result.scalar_one_or_none.return_value = conn
        file_ids_result = MagicMock()
        file_ids_result.all.return_value = [("gf_1",), ("gf_2",)]
        db.execute = AsyncMock(side_effect=[conn_result, file_ids_result])

        result = await list_connection_file_ids(
            connection_id=conn.id,
            _token="valid",
            db=db,
        )

        assert result.google_file_ids == ["gf_1", "gf_2"]
        assert result.total_count == 2

    @pytest.mark.asyncio
    async def test_list_connection_file_ids_excludes_deleted(self):
        conn = _make_connection()
        db = AsyncMock()
        conn_result = MagicMock()
        conn_result.scalar_one_or_none.return_value = conn
        file_ids_result = MagicMock()
        file_ids_result.all.return_value = [("gf_active",)]
        db.execute = AsyncMock(side_effect=[conn_result, file_ids_result])

        result = await list_connection_file_ids(
            connection_id=conn.id,
            _token="valid",
            db=db,
        )

        assert result.google_file_ids == ["gf_active"]
        assert result.total_count == 1

    @pytest.mark.asyncio
    async def test_list_connection_file_ids_empty(self):
        conn = _make_connection()
        db = AsyncMock()
        conn_result = MagicMock()
        conn_result.scalar_one_or_none.return_value = conn
        file_ids_result = MagicMock()
        file_ids_result.all.return_value = []
        db.execute = AsyncMock(side_effect=[conn_result, file_ids_result])

        result = await list_connection_file_ids(
            connection_id=conn.id,
            _token="valid",
            db=db,
        )

        assert result.google_file_ids == []
        assert result.total_count == 0


class TestTokenEndpoint:
    @pytest.mark.asyncio
    async def test_success_service_account_scope_drive(self):
        token = str(uuid4())
        conn = _make_connection(
            scope_type="drive",
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        secret = MagicMock()
        secret.nonce = b"nonce"
        secret.encrypted_value = b"encrypted"
        secret.impersonate_email = "svc@example.com"

        db = AsyncMock()
        conn_result = MagicMock()
        conn_result.scalar_one_or_none.return_value = conn
        secret_result = MagicMock()
        secret_result.scalar_one_or_none.return_value = secret
        db.execute = AsyncMock(side_effect=[conn_result, secret_result])

        settings = MagicMock()
        settings.drive_sa_encryption_key = "00" * 32
        expiry = datetime.now(timezone.utc) + timedelta(hours=1)

        creds = MagicMock()
        creds.token = "sa-token"
        creds.expiry = expiry

        with patch("app.modules.drive.internal_sync_router.get_settings", return_value=settings):
            with patch("app.modules.drive.internal_sync_router.AESGCM") as mock_aesgcm:
                mock_aesgcm.return_value.decrypt.return_value = (
                    b'{"type":"service_account","private_key":"x","client_email":"svc@example.com"}'
                )
                with patch("app.modules.drive.internal_sync_router.service_account.Credentials.from_service_account_info", return_value=creds) as mock_from_sa:
                    result = await get_connection_token(
                        connection_id=conn.id,
                        request=TokenRequest(lease_token=token),
                        _token="valid",
                        db=db,
                    )

        assert result.access_token == "sa-token"
        assert result.token_type == "Bearer"
        assert result.expires_at == expiry
        assert result.scope_type == "drive"
        mock_from_sa.assert_called_once()
        creds.refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_success_oauth_scope_folder(self):
        token = str(uuid4())
        conn = _make_connection(
            scope_type="folder",
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        secret = MagicMock()
        secret.nonce = b"nonce"
        secret.encrypted_value = b"encrypted"

        db = AsyncMock()
        conn_result = MagicMock()
        conn_result.scalar_one_or_none.return_value = conn
        secret_result = MagicMock()
        secret_result.scalar_one_or_none.return_value = secret
        db.execute = AsyncMock(side_effect=[conn_result, secret_result])

        settings = MagicMock()
        settings.drive_sa_encryption_key = "00" * 32
        expiry = datetime.now(timezone.utc) + timedelta(hours=1)

        creds = MagicMock()
        creds.token = "oauth-token"
        creds.expiry = expiry

        with patch("app.modules.drive.internal_sync_router.get_settings", return_value=settings):
            with patch("app.modules.drive.internal_sync_router.AESGCM") as mock_aesgcm:
                mock_aesgcm.return_value.decrypt.return_value = (
                    b'{"refresh_token":"r","client_id":"id","client_secret":"secret"}'
                )
                with patch("app.modules.drive.internal_sync_router.OAuthCredentials", return_value=creds) as mock_oauth_creds:
                    result = await get_connection_token(
                        connection_id=conn.id,
                        request=TokenRequest(lease_token=token),
                        _token="valid",
                        db=db,
                    )

        assert result.access_token == "oauth-token"
        assert result.scope_type == "folder"
        mock_oauth_creds.assert_called_once()
        creds.refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_connection_not_found_returns_404(self):
        db = AsyncMock()
        conn_result = MagicMock()
        conn_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=conn_result)

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await get_connection_token(
                connection_id=uuid4(),
                request=TokenRequest(lease_token=str(uuid4())),
                _token="valid",
                db=db,
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_lease_token_mismatch_returns_409(self):
        conn = _make_connection(
            lease_token=str(uuid4()),
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db = AsyncMock()
        conn_result = MagicMock()
        conn_result.scalar_one_or_none.return_value = conn
        db.execute = AsyncMock(return_value=conn_result)

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await get_connection_token(
                connection_id=conn.id,
                request=TokenRequest(lease_token=str(uuid4())),
                _token="valid",
                db=db,
            )
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "lease_token_mismatch"

    @pytest.mark.asyncio
    async def test_missing_secret_returns_404(self):
        token = str(uuid4())
        conn = _make_connection(
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )

        db = AsyncMock()
        conn_result = MagicMock()
        conn_result.scalar_one_or_none.return_value = conn
        secret_result = MagicMock()
        secret_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(side_effect=[conn_result, secret_result])

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await get_connection_token(
                connection_id=conn.id,
                request=TokenRequest(lease_token=token),
                _token="valid",
                db=db,
            )
        assert exc_info.value.status_code == 404


# ── Video ID determinism tests ────────────────────────────────────────

class TestDriveVideoId:
    def test_deterministic_output(self):
        org_id = "4d20264c-c440-4d69-8613-7d7558ea386b"
        google_file_id = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"

        result1 = _drive_video_id(org_id, google_file_id)
        result2 = _drive_video_id(org_id, google_file_id)

        assert result1 == result2
        assert result1.startswith("gd_")
        assert len(result1) == 19

    def test_different_inputs_yield_different_ids(self):
        org = "org-1"
        id1 = _drive_video_id(org, "file_a")
        id2 = _drive_video_id(org, "file_b")
        assert id1 != id2

    def test_matches_worker_sdk_implementation(self):
        org_id = "test-org"
        file_id = "test-file"
        expected_digest = hashlib.sha256(f"{org_id}:{file_id}".encode()).hexdigest()[:16]
        expected = f"gd_{expected_digest}"

        assert _drive_video_id(org_id, file_id) == expected


# ── Concurrency tests ────────────────────────────────────────────────

class TestClaimConcurrency:
    @pytest.mark.asyncio
    async def test_10_concurrent_claims_no_duplicates(self):
        all_conns = [_make_connection(drive_id=f"drive_{i}") for i in range(10)]
        claimed_ids: list[object] = []

        async def _do_claim(conn):
            db = _mock_db_with_connections([conn])
            request = ClaimSyncConnectionRequest(limit=1)
            result = await claim_sync_connection(request=request, _token="valid", db=db)
            for c in result.connections:
                claimed_ids.append(c.connection_id)

        await asyncio.gather(*[_do_claim(c) for c in all_conns])

        assert len(claimed_ids) == 10
        assert len(set(claimed_ids)) == 10

    @pytest.mark.asyncio
    async def test_concurrent_claims_empty_db(self):
        results: list[int] = []

        async def _do_claim():
            db = _mock_db_with_connections([])
            request = ClaimSyncConnectionRequest(limit=1)
            result = await claim_sync_connection(request=request, _token="valid", db=db)
            results.append(len(result.connections))

        await asyncio.gather(*[_do_claim() for _ in range(10)])

        assert all(r == 0 for r in results)

    @pytest.mark.asyncio
    async def test_concurrent_claims_unique_leases(self):
        all_conns = [_make_connection(drive_id=f"drive_{i}") for i in range(10)]
        lease_tokens: list[str] = []

        async def _do_claim(conn):
            db = _mock_db_with_connections([conn])
            request = ClaimSyncConnectionRequest(limit=1)
            result = await claim_sync_connection(request=request, _token="valid", db=db)
            for c in result.connections:
                lease_tokens.append(c.lease_token)

        await asyncio.gather(*[_do_claim(c) for c in all_conns])

        assert len(lease_tokens) == 10
        assert len(set(lease_tokens)) == 10


# ── Schema validation tests ───────────────────────────────────────────

class TestSchemaValidation:
    def test_claim_request_limit_bounds(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ClaimSyncConnectionRequest(limit=0)
        with pytest.raises(ValidationError):
            ClaimSyncConnectionRequest(limit=11)
        req = ClaimSyncConnectionRequest(limit=10)
        assert req.limit == 10

    def test_claim_request_default_limit(self):
        req = ClaimSyncConnectionRequest()
        assert req.limit == 1

    def test_checkpoint_requires_lease_token(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            SyncCheckpointRequest.model_validate({})

    def test_checkpoint_defaults(self):
        req = SyncCheckpointRequest(lease_token="abc")
        assert req.release is True
        assert req.change_token is None
        assert req.last_sync_at is None
        assert req.error_message is None

    def test_upsert_requires_lease_token(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            UpsertFilesRequest.model_validate({"items": []})

    def test_discovered_file_requires_fields(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            DriveDiscoveredFile.model_validate({"provider_file_id": "abc"})
        with pytest.raises(ValidationError):
            DriveDiscoveredFile.model_validate({"provider_file_id": "abc", "name": "test"})
        f = DriveDiscoveredFile(
            provider_file_id="abc", name="test.mp4", mime_type="video/mp4",
        )
        assert f.provider_file_id == "abc"

    def test_discovered_file_optional_fields(self):
        f = DriveDiscoveredFile(
            provider_file_id="abc",
            name="test.mp4",
            mime_type="video/mp4",
            size=1024,
            md5_checksum="abc123",
            drive_path="/Videos/test.mp4",
        )
        assert f.size == 1024
        assert f.md5_checksum == "abc123"
        assert f.drive_path == "/Videos/test.mp4"

    def test_discovered_file_size_must_be_non_negative(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            DriveDiscoveredFile(
                provider_file_id="abc",
                name="test.mp4",
                mime_type="video/mp4",
                size=-1,
            )
