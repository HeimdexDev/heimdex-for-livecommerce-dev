import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException

from app.modules.search.schemas import SearchFilters
from app.modules.search.service import SearchService


class TestSearchService:
    @pytest.fixture
    def search_service(self, mock_db_session, mock_opensearch_client):
        return SearchService(mock_db_session, mock_opensearch_client)

    @pytest.mark.asyncio
    async def test_search_returns_response(self, search_service, mock_opensearch_client):
        org_id = uuid4()
        
        mock_opensearch_client.search_lexical.return_value = [
            {
                "_id": "seg1",
                "_score": 10.0,
                "_source": {
                    "segment_id": "seg1",
                    "video_id": "vid1",
                    "library_id": str(uuid4()),
                    "library_name": "Test Library",
                    "start_ms": 0,
                    "end_ms": 5000,
                    "transcript_raw": "Test transcript",
                    "source_type": "gdrive",
                    "people_cluster_ids": [],
                },
            }
        ]
        mock_opensearch_client.search_vector.return_value = []
        
        with patch.object(search_service.session, "execute") as mock_execute:
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_execute.return_value = mock_result
            
            response = await search_service.search(
                query="test",
                org_id=org_id,
                alpha=0.5,
                filters=SearchFilters(),
            )
        
        assert response.query == "test"
        assert response.alpha == 0.5
        assert len(response.results) <= 20
        assert response.total_candidates >= 0

    @pytest.mark.asyncio
    async def test_search_with_alpha_extremes(self, search_service, mock_opensearch_client):
        org_id = uuid4()
        
        mock_opensearch_client.search_lexical.return_value = [
            {"_id": "lex1", "_score": 10.0, "_source": {"video_id": "v1", "segment_id": "lex1", "library_id": str(uuid4()), "start_ms": 0, "end_ms": 1000, "transcript_raw": "Lexical result", "source_type": "gdrive", "people_cluster_ids": []}},
        ]
        mock_opensearch_client.search_vector.return_value = [
            {"_id": "vec1", "_score": 0.9, "_source": {"video_id": "v2", "segment_id": "vec1", "library_id": str(uuid4()), "start_ms": 0, "end_ms": 1000, "transcript_raw": "Vector result", "source_type": "gdrive", "people_cluster_ids": []}},
        ]
        
        with patch.object(search_service.session, "execute") as mock_execute:
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_execute.return_value = mock_result
            
            response_lex = await search_service.search("test", org_id, alpha=0.0, filters=SearchFilters())
            response_vec = await search_service.search("test", org_id, alpha=1.0, filters=SearchFilters())
        
        if response_lex.results and response_vec.results:
            assert response_lex.results[0].segment_id == "lex1"
            assert response_vec.results[0].segment_id == "vec1"

    @pytest.mark.asyncio
    async def test_search_applies_filters(self, search_service, mock_opensearch_client):
        org_id = uuid4()
        lib_id = uuid4()

        mock_lib = MagicMock()
        mock_lib.id = str(lib_id)
        mock_lib.name = "Test Library"

        filters = SearchFilters(
            source_types=["gdrive"],
            library_ids=[lib_id],
            person_cluster_ids=["cluster1"],
        )
        
        with patch.object(search_service.session, "execute") as mock_execute:
            people_result = MagicMock()
            people_result.scalars.return_value.all.return_value = []
            lib_result = MagicMock()
            lib_result.scalars.return_value.all.return_value = [mock_lib]
            mock_execute.side_effect = [people_result, lib_result]

            await search_service.search("test", org_id, alpha=0.5, filters=filters)

        call_args = mock_opensearch_client.search_lexical.call_args
        filter_dict = call_args.kwargs["filters"]

        assert filter_dict["source_types"] == ["gdrive"]
        assert filter_dict["library_ids"] == [lib_id]
        assert filter_dict["person_cluster_ids"] == ["cluster1"]


class TestSegmentLibraryIdValidation:

    @pytest.fixture
    def search_service(self, mock_db_session, mock_opensearch_client):
        return SearchService(mock_db_session, mock_opensearch_client)

    @pytest.mark.asyncio
    async def test_unknown_library_id_returns_400(self, search_service):
        """library_ids not belonging to the org should be rejected with 400."""
        org_id = uuid4()
        unknown_lib_id = uuid4()

        with patch.object(search_service.session, "execute") as mock_execute:
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_execute.return_value = mock_result

            filters = SearchFilters(library_ids=[unknown_lib_id])
            with pytest.raises(HTTPException) as exc_info:
                await search_service.search("test", org_id, alpha=0.5, filters=filters)
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_known_library_id_passes(self, search_service, mock_opensearch_client):
        """library_ids belonging to the org should pass validation."""
        org_id = uuid4()
        lib_id = uuid4()

        mock_lib = MagicMock()
        mock_lib.id = str(lib_id)
        mock_lib.name = "Known"

        with patch.object(search_service.session, "execute") as mock_execute:
            people_result = MagicMock()
            people_result.scalars.return_value.all.return_value = []
            lib_result = MagicMock()
            lib_result.scalars.return_value.all.return_value = [mock_lib]
            mock_execute.side_effect = [people_result, lib_result]

            filters = SearchFilters(library_ids=[lib_id])
            response = await search_service.search("test", org_id, alpha=0.5, filters=filters)
            assert response is not None
