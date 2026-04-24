"""Regression tests for metadata-mode video diversification bug.

Prior behavior (pre-2026-04-24): ``_search_metadata`` called
``diversify_results(max_per_video=4, target_count=20)`` over a scene-
inflated candidate pool. When a metadata query matches a video title,
every scene of that video shares the same BM25 score — the top-200
scene pool was dominated by a handful of videos, each contributing
many scenes. The diversifier then capped output at 20 scenes with
max 4 per video → exactly 5 unique videos surfaced regardless of how
many videos actually matched.

Confirmed on livenow prod 2026-04-24:
    센트룸 → 6174 scene docs / 142 unique videos / UI showed 4
    하림   → 3182 scene docs /  82 unique videos / UI showed 5

Fix: request OpenSearch to ``collapse`` on ``video_id`` (one hit per
unique video) and skip per-video diversification in metadata mode.
Pair with a cardinality aggregation so ``total_candidates`` reflects
the true distinct-video count, not the fetched page.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.search.schemas import SearchFilters, VideoSearchResponse
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
    """Helper: stub the OS client methods used by _search_metadata."""
    os_client.search_vector = AsyncMock(return_value=[])
    os_client.search_visual_vector = AsyncMock(return_value=[])
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
class TestMetadataCollapse:
    async def test_passes_collapse_by_video_to_search_metadata(
        self, search_service, org_id
    ):
        svc, os_client = search_service
        _wire_mocks(os_client)
        os_client.search_metadata = AsyncMock(return_value=[])

        await svc.search(
            query="센트룸",
            org_id=org_id,
            alpha=0.5,
            filters=SearchFilters(),
            search_mode="metadata",
        )

        os_client.search_metadata.assert_called_once()
        call_kwargs = os_client.search_metadata.call_args.kwargs
        assert call_kwargs["collapse_by_video"] is True
        # ``size`` must be large enough to cover page_size_max; a bug that
        # shipped this as 20 or left it at the legacy 200 would re-
        # introduce the cap when users bump page_size.
        assert call_kwargs["size"] >= svc.settings.search_page_size_max

    async def test_returns_one_video_per_collapsed_hit(
        self, search_service, org_id
    ):
        """With collapse on, each hit already represents a distinct video.
        Service must not re-diversify them away."""
        svc, os_client = search_service
        _wire_mocks(os_client)
        # Simulate OS having collapsed to 30 distinct videos
        hits = [
            _make_metadata_hit(f"s_{i}", f"vid_{i:03d}", score=100.0 - i)
            for i in range(30)
        ]
        # Planted sentinel mirrors production cardinality agg
        hits[0]["_source"]["_heimdex_unique_videos"] = 142
        os_client.search_metadata = AsyncMock(return_value=hits)

        res = await svc.search(
            query="센트룸",
            org_id=org_id,
            alpha=0.5,
            filters=SearchFilters(),
            search_mode="metadata",
        )

        assert isinstance(res, VideoSearchResponse)
        # Default page_size=20 → 20 video results (not 5 under the old cap)
        assert len(res.results) == 20
        # All distinct
        assert len({v.video_id for v in res.results}) == 20

    async def test_surfaces_true_total_from_cardinality_sentinel(
        self, search_service, org_id
    ):
        svc, os_client = search_service
        _wire_mocks(os_client)
        hits = [
            _make_metadata_hit(f"s_{i}", f"vid_{i:03d}", score=100.0 - i)
            for i in range(10)
        ]
        hits[0]["_source"]["_heimdex_unique_videos"] = 142
        os_client.search_metadata = AsyncMock(return_value=hits)

        res = await svc.search(
            query="센트룸",
            org_id=org_id,
            alpha=0.5,
            filters=SearchFilters(),
            search_mode="metadata",
        )

        # Should report the TRUE distinct-video count, not the fetched
        # page length. Prevents "4 videos" confusion on matching corpora
        # larger than page_size.
        assert res.total_candidates == 142

    async def test_missing_sentinel_falls_back_to_len_ranked_items(
        self, search_service, org_id
    ):
        """Older OS responses (pre-collapse feature, or OS indices that
        don't support doc_values on video_id) arrive with no sentinel.
        Service must still return a valid response, falling back to
        counting distinct video_ids in the ranked list."""
        svc, os_client = search_service
        _wire_mocks(os_client)
        hits = [
            _make_metadata_hit(f"s_{i}", f"vid_{i:03d}", score=100.0 - i)
            for i in range(5)
        ]
        # No sentinel planted
        os_client.search_metadata = AsyncMock(return_value=hits)

        res = await svc.search(
            query="센트룸",
            org_id=org_id,
            alpha=0.5,
            filters=SearchFilters(),
            search_mode="metadata",
        )

        assert res.total_candidates == 5
        assert len(res.results) == 5

    async def test_sentinel_stripped_from_downstream_results(
        self, search_service, org_id
    ):
        """The ``_heimdex_unique_videos`` sentinel must not leak into
        the first scene's SceneResult (would surface an unknown field
        through the public API)."""
        svc, os_client = search_service
        _wire_mocks(os_client)
        hits = [
            _make_metadata_hit("s_0", "vid_000", score=100.0),
            _make_metadata_hit("s_1", "vid_001", score=99.0),
        ]
        hits[0]["_source"]["_heimdex_unique_videos"] = 50
        os_client.search_metadata = AsyncMock(return_value=hits)

        res = await svc.search(
            query="센트룸",
            org_id=org_id,
            alpha=0.5,
            filters=SearchFilters(),
            search_mode="metadata",
        )

        # Nothing in the results payload should carry the sentinel.
        for video in res.results:
            dumped = video.model_dump()
            assert "_heimdex_unique_videos" not in str(dumped)

    async def test_respects_page_size_override(self, search_service, org_id):
        svc, os_client = search_service
        _wire_mocks(os_client)
        hits = [
            _make_metadata_hit(f"s_{i}", f"vid_{i:03d}", score=100.0 - i)
            for i in range(60)
        ]
        os_client.search_metadata = AsyncMock(return_value=hits)

        res = await svc.search(
            query="센트룸",
            org_id=org_id,
            alpha=0.5,
            filters=SearchFilters(),
            search_mode="metadata",
            page_size=60,
        )

        assert len(res.results) == 60
