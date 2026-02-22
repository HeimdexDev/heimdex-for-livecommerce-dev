from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.drive.repository import DriveFileRepository


def _result_with_ids(*ids):
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = list(ids)
    result.scalars.return_value = scalars
    return result


@pytest.mark.asyncio
async def test_reap_stuck_processing_file_reset_to_pending():
    session = AsyncMock()
    file_id = uuid4()
    session.execute = AsyncMock(
        side_effect=[
            _result_with_ids(file_id),
            _result_with_ids(),
            _result_with_ids(),
            _result_with_ids(),
        ]
    )

    repo = DriveFileRepository(session)
    reaped_count = await repo.reap_stuck_files(30)

    assert reaped_count == 1
    processing_stmt = session.execute.call_args_list[0].args[0]
    stmt_sql = str(processing_stmt)
    assert "processing_status" in stmt_sql
    assert "processing_status IN" in stmt_sql
    assert "retry_count" in stmt_sql
    assert "INTERVAL '30 minutes'" in stmt_sql
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_reap_respects_max_retries():
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _result_with_ids(),
            _result_with_ids(),
            _result_with_ids(),
            _result_with_ids(),
        ]
    )

    repo = DriveFileRepository(session)
    reaped_count = await repo.reap_stuck_files(30)

    assert reaped_count == 0
    processing_stmt = session.execute.call_args_list[0].args[0]
    assert "max_retries" in str(processing_stmt)


@pytest.mark.asyncio
async def test_reap_skips_files_with_recent_heartbeat():
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _result_with_ids(),
            _result_with_ids(),
            _result_with_ids(),
            _result_with_ids(),
        ]
    )

    repo = DriveFileRepository(session)
    reaped_count = await repo.reap_stuck_files(10)

    assert reaped_count == 0
    processing_stmt = session.execute.call_args_list[0].args[0]
    assert "last_heartbeat_at" in str(processing_stmt)
    assert "INTERVAL '10 minutes'" in str(processing_stmt)


@pytest.mark.asyncio
async def test_reap_stuck_stt_running_reset():
    session = AsyncMock()
    file_id = uuid4()
    session.execute = AsyncMock(
        side_effect=[
            _result_with_ids(),
            _result_with_ids(file_id),
            _result_with_ids(),
            _result_with_ids(),
        ]
    )

    repo = DriveFileRepository(session)
    reaped_count = await repo.reap_stuck_files(30)

    assert reaped_count == 1
    stt_stmt = session.execute.call_args_list[1].args[0]
    stt_sql = str(stt_stmt)
    assert "stt_status" in stt_sql
    assert "enrichment_state" in stt_sql


@pytest.mark.asyncio
async def test_reap_stuck_ocr_running_reset():
    session = AsyncMock()
    file_id = uuid4()
    session.execute = AsyncMock(
        side_effect=[
            _result_with_ids(),
            _result_with_ids(),
            _result_with_ids(file_id),
            _result_with_ids(),
        ]
    )

    repo = DriveFileRepository(session)
    reaped_count = await repo.reap_stuck_files(30)

    assert reaped_count == 1
    ocr_stmt = session.execute.call_args_list[2].args[0]
    ocr_sql = str(ocr_stmt)
    assert "ocr_status" in ocr_sql
    assert "enrichment_state" in ocr_sql


@pytest.mark.asyncio
async def test_reap_stuck_caption_running_reset():
    session = AsyncMock()
    file_id = uuid4()
    session.execute = AsyncMock(
        side_effect=[
            _result_with_ids(),
            _result_with_ids(),
            _result_with_ids(),
            _result_with_ids(file_id),
        ]
    )

    repo = DriveFileRepository(session)
    reaped_count = await repo.reap_stuck_files(30)

    assert reaped_count == 1
    caption_stmt = session.execute.call_args_list[3].args[0]
    caption_sql = str(caption_stmt)
    assert "caption_status" in caption_sql
    assert "enrichment_state" in caption_sql


@pytest.mark.asyncio
async def test_update_heartbeat_sets_timestamp():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_result_with_ids(uuid4()))

    repo = DriveFileRepository(session)
    updated_count = await repo.update_heartbeat(uuid4())

    assert updated_count == 1
    stmt = session.execute.call_args.args[0]
    assert "last_heartbeat_at" in str(stmt)
    assert "now()" in str(stmt)
    session.flush.assert_awaited_once()
