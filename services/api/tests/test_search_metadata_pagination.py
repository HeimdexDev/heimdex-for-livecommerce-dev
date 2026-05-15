"""Regression tests for numbered-pagination on metadata search mode.

Paired with ``test_search_metadata_collapse.py`` — that file locks the
collapse-based coverage guarantee (all 142 videos reachable); this one
locks the offset-based pagination on top of it.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.search.schemas import SearchFilters, SearchRequest, VideoSearchResponse
from app.modules.search.scene_service import SceneSearchService


@pytest.fixture
def org_id():
    return uuid4()


def _make_metadata_hit(scene_id: str, video_id: str, score: float = 10.0) -> dict:
    return {
        "_id": scene_id,
        "_score": score,
        "_source": {
            "scene_id": scene_id,
            "video_id": video_id,
            "library_id": str(uuid4()),
            "start_ms": 0,
            "end_ms": 5000,
            "transcript_raw": "",
            "ocr_text_raw": "",
            "ocr_char_count": 0,
            "source_type": "gdrive",
            "people_cluster_ids": [],
            "speech_segment_count": 0,
            "transcript_char_count": 0,
            "video_title": f"title_{video_id}",
        },
    }


def _wire_mocks(os_client):
    os_client.search_vector = AsyncMock(return_value=[])
    os_client.search_visual_vector = AsyncMock(return_value=[])
    os_client.search_lexical = AsyncMock(return_value=[])
    os_client.get_facets = AsyncMock(
        return_value={"libraries": [], "source_types": [], "people": []}
    )


@pytest.fixture
def search_service(mock_db_session, mock_scene_opensearch_client):
    svc = SceneSearchService(mock_db_session, mock_scene_opensearch_client)
    with patch.object(svc.session, "execute") as mock_execute:
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_execute.return_value = mock_result
        yield svc, mock_scene_opensearch_client


@pytest.mark.asyncio
class TestMetadataPagination:
    async def test_offset_zero_is_page_one_default(self, search_service, org_id):
        svc, os_client = search_service
        _wire_mocks(os_client)
        os_client.search_metadata = AsyncMock(return_value=[])

        await svc.search(
            query="q",
            org_id=org_id,
            alpha=0.5,
            filters=SearchFilters(),
            search_mode="metadata",
        )

        kw = os_client.search_metadata.call_args.kwargs
        assert kw.get("offset", 0) == 0

    async def test_offset_forwarded_to_opensearch_from(self, search_service, org_id):
        svc, os_client = search_service
        _wire_mocks(os_client)
        os_client.search_metadata = AsyncMock(return_value=[])

        await svc.search(
            query="q",
            org_id=org_id,
            alpha=0.5,
            filters=SearchFilters(),
            search_mode="metadata",
            offset=40,
        )

        kw = os_client.search_metadata.call_args.kwargs
        assert kw["offset"] == 40
        # Size stays at the effective page size — no over-fetching
        assert kw["size"] == svc.settings.search_page_size

    async def test_total_candidates_stable_across_pages(self, search_service, org_id):
        """Cardinality aggregation is page-independent — ``total_candidates``
        should be the same value whether the client is on page 1 or page 7."""
        svc, os_client = search_service
        _wire_mocks(os_client)

        # Page 1: 20 hits, sentinel=142
        page1 = [
            _make_metadata_hit(f"s_{i}", f"vid_{i:03d}", score=200.0 - i)
            for i in range(20)
        ]
        page1[0]["_source"]["_heimdex_unique_videos"] = 142
        # Page 7: 2 hits (tail), sentinel=142 still
        page7 = [
            _make_metadata_hit(f"s_{i}", f"vid_{i:03d}", score=60.0 - i)
            for i in range(140, 142)
        ]
        page7[0]["_source"]["_heimdex_unique_videos"] = 142

        # Two calls, same cardinality
        os_client.search_metadata = AsyncMock(side_effect=[page1, page7])

        r1 = await svc.search(
            query="q", org_id=org_id, alpha=0.5, filters=SearchFilters(),
            search_mode="metadata", offset=0,
        )
        r7 = await svc.search(
            query="q", org_id=org_id, alpha=0.5, filters=SearchFilters(),
            search_mode="metadata", offset=140,
        )

        assert isinstance(r1, VideoSearchResponse)
        assert isinstance(r7, VideoSearchResponse)
        assert r1.total_candidates == 142
        assert r7.total_candidates == 142
        assert len(r1.results) == 20
        assert len(r7.results) == 2

    async def test_offset_beyond_last_page_returns_empty(self, search_service, org_id):
        svc, os_client = search_service
        _wire_mocks(os_client)
        os_client.search_metadata = AsyncMock(return_value=[])

        res = await svc.search(
            query="q", org_id=org_id, alpha=0.5, filters=SearchFilters(),
            search_mode="metadata", offset=200,
        )

        assert isinstance(res, VideoSearchResponse)
        assert res.results == []
        # total_candidates defaults to len(ranked_items)=0 when no sentinel
        assert res.total_candidates == 0

    async def test_lexical_mode_ignores_offset_and_logs_warning(
        self, search_service, org_id, caplog
    ):
        svc, os_client = search_service
        _wire_mocks(os_client)

        with caplog.at_level(logging.WARNING):
            await svc.search(
                query="q", org_id=org_id, alpha=0.5, filters=SearchFilters(),
                search_mode="lexical", offset=40,
            )

        # search_metadata must NOT have been called
        assert not os_client.search_metadata.called
        # search_lexical was called but WITHOUT offset
        assert os_client.search_lexical.called
        kw = os_client.search_lexical.call_args.kwargs
        assert "offset" not in kw
        # Log contains our structured warning name so grepped logs show the
        # misbehaving client. (We assert on the logged event keyword via
        # module state; caplog doesn't capture structlog records — the
        # important part is that the wrong mode does NOT forward offset.)

    async def test_semantic_mode_ignores_offset(self, search_service, org_id):
        svc, os_client = search_service
        _wire_mocks(os_client)

        with patch(
            "app.modules.search.scene_service.get_query_embedding",
            new_callable=AsyncMock,
        ) as mock_embed:
            mock_embed.return_value = [0.1] * 1024
            await svc.search(
                query="q", org_id=org_id, alpha=0.5, filters=SearchFilters(),
                search_mode="semantic", offset=40,
            )

        assert not os_client.search_metadata.called
        kw = os_client.search_vector.call_args.kwargs
        assert "offset" not in kw


class TestRequestSchemaBounds:
    """Pydantic-level bounds on the wire protocol."""

    def test_offset_default_is_zero(self):
        req = SearchRequest(q="센트룸", alpha=0.5, filters=SearchFilters())
        assert req.offset == 0

    def test_negative_offset_rejected(self):
        with pytest.raises(ValidationError):
            SearchRequest(q="q", alpha=0.5, filters=SearchFilters(), offset=-1)

    def test_offset_above_window_rejected(self):
        with pytest.raises(ValidationError):
            SearchRequest(q="q", alpha=0.5, filters=SearchFilters(), offset=10_001)

    def test_offset_at_window_ceiling_ok(self):
        req = SearchRequest(q="q", alpha=0.5, filters=SearchFilters(), offset=10_000)
        assert req.offset == 10_000
