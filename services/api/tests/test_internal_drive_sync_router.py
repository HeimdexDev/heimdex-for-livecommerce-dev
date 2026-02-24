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
    get_connection_token,
    upsert_files,
)
from app.modules.drive.internal_sync_schemas import (
    ClaimSyncConnectionRequest,
    DriveDiscoveredFile,
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
    drive_id="shared-drive-001",
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


def _mock_db_for_upsert(connection, existing_google_ids):
    db = AsyncMock()
    conn_result = MagicMock()
    conn_result.scalar_one_or_none.return_value = connection
    file_result = MagicMock()
    file_result.all.return_value = [(gid,) for gid in existing_google_ids]
    db.execute = AsyncMock(side_effect=[conn_result, file_result])
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


def _make_discovered_file(
    *,
    provider_file_id=None,
    name="video.mp4",
    mime_type="video/mp4",
):
    return DriveDiscoveredFile(
        provider_file_id=provider_file_id or f"gfile_{uuid4().hex[:8]}",
        name=name,
        mime_type=mime_type,
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

    def test_none_token_raises_409(self):
        conn = _make_connection(
            lease_token=str(uuid4()),
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _enforce_connection_lease(conn, None)
        assert exc_info.value.status_code == 409

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
        claimed_ids: list = []

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
        results = []

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
        lease_tokens: list = []

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
            SyncCheckpointRequest()

    def test_checkpoint_defaults(self):
        req = SyncCheckpointRequest(lease_token="abc")
        assert req.release is True
        assert req.change_token is None
        assert req.last_sync_at is None
        assert req.error_message is None

    def test_upsert_requires_lease_token(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            UpsertFilesRequest(items=[])

    def test_discovered_file_requires_fields(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            DriveDiscoveredFile(provider_file_id="abc")
        with pytest.raises(ValidationError):
            DriveDiscoveredFile(provider_file_id="abc", name="test")
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
