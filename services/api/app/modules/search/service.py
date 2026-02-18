from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.logging_config import get_logger
from app.modules.libraries.repository import LibraryRepository
from app.modules.people.repository import (
    PeopleClusterLabelRepository,
    PeopleExcludePreferenceRepository,
)
from app.modules.search.client import OpenSearchClient
from app.modules.search.embedding import get_query_embedding
from app.modules.search.fusion import compute_weighted_rrf, diversify_results
from app.modules.search.schemas import (
    DebugInfo,
    Facets,
    FacetItem,
    SearchFilters,
    SearchResponse,
    SegmentResult,
)

logger = get_logger(__name__)


class SearchService:
    def __init__(self, session: AsyncSession, opensearch: OpenSearchClient):
        self.session = session
        self.opensearch = opensearch
        self.settings = get_settings()

    async def search(
        self,
        query: str,
        org_id: UUID,
        alpha: float,
        filters: SearchFilters,
        user_id: UUID | None = None,
    ) -> SearchResponse:
        logger.info(
            "search_started",
            org_id=str(org_id),
            query=query[:50],
            alpha=alpha,
        )

        people_repo = PeopleClusterLabelRepository(self.session)
        people_labels = await people_repo.list_by_org(org_id)
        people_label_map = {p.person_cluster_id: p.label for p in people_labels}

        exclude_ids_not_in = list(filters.person_cluster_ids_not_in or [])
        if user_id is not None:
            exclude_repo = PeopleExcludePreferenceRepository(self.session)
            user_excludes = await exclude_repo.list_by_user(org_id, user_id)
            if user_excludes:
                exclude_ids_not_in = list(set(exclude_ids_not_in + user_excludes))

        matched_person_cluster_ids: list[str] = []
        for p in people_labels:
            if p.label and p.label.strip() and p.label.strip() in query:
                matched_person_cluster_ids.append(p.person_cluster_id)

        effective_person_ids = list(filters.person_cluster_ids or [])
        if matched_person_cluster_ids:
            effective_person_ids = list(set(effective_person_ids + matched_person_cluster_ids))
            logger.info(
                "person_name_detected_in_query",
                query=query[:50],
                matched_labels=[people_label_map.get(pid) for pid in matched_person_cluster_ids],
                matched_cluster_ids=matched_person_cluster_ids,
            )

        filter_dict = {
            "date_from": filters.date_from,
            "date_to": filters.date_to,
            "source_types": filters.source_types,
            "library_ids": filters.library_ids,
            "person_cluster_ids": effective_person_ids or None,
            "person_cluster_ids_not_in": exclude_ids_not_in or None,
        }

        query_embedding = await get_query_embedding(query)

        lexical_results = await self.opensearch.search_lexical(
            query=query,
            org_id=str(org_id),
            filters=filter_dict,
            size=self.settings.search_lexical_top_k,
            matched_person_cluster_ids=matched_person_cluster_ids or None,
        )
        
        vector_results = await self.opensearch.search_vector(
            embedding=query_embedding,
            org_id=str(org_id),
            filters=filter_dict,
            size=self.settings.search_vector_top_k,
        )
        
        ranked_items = compute_weighted_rrf(lexical_results, vector_results, alpha)
        
        diversified = diversify_results(
            ranked_items,
            max_per_video=self.settings.search_max_scenes_per_video,
            target_count=self.settings.search_page_size,
        )
        
        library_repo = LibraryRepository(self.session)
        libraries = await library_repo.list_by_org(org_id)
        library_map = {str(lib.id): lib.name for lib in libraries}

        if filters.library_ids:
            requested = {str(lid) for lid in filters.library_ids}
            unknown = requested - set(library_map.keys())
            if unknown:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown library_ids: {sorted(unknown)}",
                )

        results = []
        for item in diversified:
             src = item.source
             results.append(
                 SegmentResult(
                     segment_id=src.get("segment_id", item.doc_id),
                     video_id=src.get("video_id", ""),
                     video_title=src.get("video_title"),
                     library_id=UUID(src.get("library_id", "00000000-0000-0000-0000-000000000000")),
                     library_name=library_map.get(src.get("library_id", ""), "Unknown"),
                     start_ms=src.get("start_ms", 0),
                     end_ms=src.get("end_ms", 0),
                     snippet=src.get("transcript_raw", "")[:500],
                     thumbnail_url=src.get("thumbnail_url"),
                     source_type=src.get("source_type", "gdrive"),
                     required_drive_nickname=src.get("required_drive_nickname"),
                     capture_time=src.get("capture_time"),
                     people_cluster_ids=src.get("people_cluster_ids", []),
                     keyframe_timestamp_ms=src.get("keyframe_timestamp_ms", 0),
                     debug=DebugInfo(
                        lexical_rank=item.lexical_rank,
                        lexical_score=item.lexical_score,
                        vector_rank=item.vector_rank,
                        vector_score=item.vector_score,
                        lexical_contribution=item.lexical_contribution,
                        vector_contribution=item.vector_contribution,
                        fused_score=item.fused_score,
                        quality_factor=item.quality_factor,
                        adjusted_score=item.adjusted_score,
                        diversification_penalty=item.diversification_penalty,
                    ),
                )
            )
        
        facet_data = await self.opensearch.get_facets(str(org_id), filter_dict)
        
        facets = Facets(
            libraries=[
                FacetItem(
                    value=bucket["key"],
                    count=bucket["doc_count"],
                    label=library_map.get(bucket["key"]),
                )
                for bucket in facet_data.get("libraries", [])
            ],
            source_types=[
                FacetItem(
                    value=bucket["key"],
                    count=bucket["doc_count"],
                    label=bucket["key"],
                )
                for bucket in facet_data.get("source_types", [])
            ],
            people_cluster_ids=[
                FacetItem(
                    value=bucket["key"],
                    count=bucket["doc_count"],
                    label=people_label_map.get(bucket["key"]),
                )
                for bucket in facet_data.get("people", [])
            ],
        )
        
        logger.info(
            "search_completed",
            org_id=str(org_id),
            result_count=len(results),
            total_candidates=len(ranked_items),
        )
        
        return SearchResponse(
            results=results,
            total_candidates=len(ranked_items),
            facets=facets,
            query=query,
            alpha=alpha,
        )
