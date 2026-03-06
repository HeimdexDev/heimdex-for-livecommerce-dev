from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.search.models import SearchEvent
from app.modules.search.search_event_repository import SearchEventRepository
from app.modules.search.router import (
    _build_metadata,
    _extract_result_count,
    _record_search_event,
)
from app.modules.search.schemas import SearchFilters, SearchRequest


class TestSearchEventModel:

    def test_tablename(self):
        assert SearchEvent.__tablename__ == "search_events"

    def test_composite_pk(self):
        pk_cols = [c.name for c in SearchEvent.__table__.primary_key]
        assert "id" in pk_cols
        assert "created_at" in pk_cols

    def test_metadata_column_name(self):
        col = SearchEvent.__table__.c["metadata"]
        assert col is not None


class TestSearchEventRepository:

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def repo(self, mock_session):
        return SearchEventRepository(mock_session)

    @pytest.mark.asyncio
    async def test_create_adds_event(self, repo, mock_session):
        org_id = uuid4()
        user_id = uuid4()

        await repo.create(
            org_id=org_id,
            user_id=user_id,
            query_text="test query",
            search_mode="lexical",
            result_count=10,
            response_ms=42,
            metadata={"alpha": 0.5},
        )

        mock_session.add.assert_called_once()
        event = mock_session.add.call_args[0][0]
        assert isinstance(event, SearchEvent)
        assert event.org_id == org_id
        assert event.user_id == user_id
        assert event.query_text == "test query"
        assert event.search_mode == "lexical"
        assert event.result_count == 10
        assert event.response_ms == 42
        assert event.metadata_ == {"alpha": 0.5}

    @pytest.mark.asyncio
    async def test_create_defaults_metadata_to_empty_dict(self, repo, mock_session):
        await repo.create(
            org_id=uuid4(),
            user_id=uuid4(),
            query_text="q",
            search_mode="semantic",
        )
        event = mock_session.add.call_args[0][0]
        assert event.metadata_ == {}

    @pytest.mark.asyncio
    async def test_count_by_org(self, repo, mock_session):
        mock_session.execute.return_value = MagicMock(scalar_one=MagicMock(return_value=5))
        count = await repo.count_by_org(uuid4())
        assert count == 5

    @pytest.mark.asyncio
    async def test_ensure_partitions_creates_correct_count(self, repo, mock_session):
        partitions = await repo.ensure_partitions(months_ahead=2)
        assert len(partitions) == 3
        assert all(p.startswith("search_events_") for p in partitions)

    @pytest.mark.asyncio
    async def test_ensure_partitions_format(self, repo, mock_session):
        partitions = await repo.ensure_partitions(months_ahead=0)
        assert len(partitions) == 1
        now = datetime.now(timezone.utc)
        expected = f"search_events_{now.year}_{now.month:02d}"
        assert partitions[0] == expected

    @pytest.mark.asyncio
    async def test_ensure_partitions_executes_ddl(self, repo, mock_session):
        await repo.ensure_partitions(months_ahead=1)
        assert mock_session.execute.call_count == 2
        for call in mock_session.execute.call_args_list:
            sql = str(call[0][0].text)
            assert "CREATE TABLE IF NOT EXISTS" in sql
            assert "PARTITION OF search_events" in sql


class TestExtractResultCount:

    def test_with_total_candidates(self):
        resp = MagicMock(total_candidates=42)
        assert _extract_result_count(resp) == 42

    def test_without_total_candidates(self):
        resp = MagicMock(spec=[])
        assert _extract_result_count(resp) is None


class TestBuildMetadata:

    def test_basic_metadata(self):
        req = SearchRequest(q="hello", alpha=0.7, group_by="video")
        meta = _build_metadata(req)
        assert meta["alpha"] == 0.7
        assert meta["group_by"] == "video"

    def test_with_date_filters(self):
        dt = datetime(2026, 3, 1, tzinfo=timezone.utc)
        req = SearchRequest(
            q="test",
            filters=SearchFilters(date_from=dt, date_to=dt),
        )
        meta = _build_metadata(req)
        assert "date_from" in meta
        assert "date_to" in meta

    def test_without_optional_filters(self):
        req = SearchRequest(q="test")
        meta = _build_metadata(req)
        assert "date_from" not in meta
        assert "source_types" not in meta
        assert "person_cluster_ids" not in meta

    def test_with_include_ocr(self):
        req = SearchRequest(q="test", include_ocr=True)
        meta = _build_metadata(req)
        assert meta["include_ocr"] is True

    def test_without_include_ocr(self):
        req = SearchRequest(q="test")
        meta = _build_metadata(req)
        assert "include_ocr" not in meta


class TestRecordSearchEvent:

    @pytest.mark.asyncio
    async def test_records_event_successfully(self):
        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)

        with patch(
            "app.db.base.get_async_session_factory",
            return_value=mock_factory,
        ), patch(
            "app.modules.search.search_event_repository.SearchEventRepository"
        ) as MockRepo:
            mock_repo = AsyncMock()
            MockRepo.return_value = mock_repo

            await _record_search_event(
                org_id=uuid4(),
                user_id=uuid4(),
                query_text="test",
                search_mode="lexical",
                result_count=5,
                response_ms=100,
            )

            mock_repo.create.assert_called_once()
            mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_swallows_exceptions(self):
        with patch(
            "app.db.base.get_async_session_factory",
            side_effect=Exception("db error"),
        ):
            await _record_search_event(
                org_id=uuid4(),
                user_id=uuid4(),
                query_text="test",
                search_mode="lexical",
                result_count=None,
                response_ms=None,
            )
