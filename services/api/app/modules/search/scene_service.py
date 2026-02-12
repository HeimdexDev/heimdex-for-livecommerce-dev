"""
Scene search service.

Orchestrates hybrid lexical + semantic retrieval over the scenes index,
reusing the same RRF fusion and diversification logic as segment search.

Scenes are pre-computed atomic search units — this service does NOT
aggregate segments into scenes. It treats each scene document as an
independent candidate.
"""
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.logging_config import get_logger
from app.modules.libraries.repository import LibraryRepository
from app.modules.people.repository import PeopleClusterLabelRepository
from app.modules.search.embedding import get_query_embedding
from app.modules.search.fusion import compute_weighted_rrf, diversify_results
from app.modules.search.scene_client import SceneSearchClient
from app.modules.search.schemas import (
    DebugInfo,
    Facets,
    FacetItem,
    SceneResult,
    SceneSearchResponse,
    SearchFilters,
)

logger = get_logger(__name__)


class SceneSearchService:
    """Search service for the scenes index.

    Follows the same retrieval → fusion → diversification pipeline
    as ``SearchService`` but queries ``SceneSearchClient`` and returns
    ``SceneSearchResponse`` with ``SceneResult`` items.
    """

    def __init__(self, session: AsyncSession, scene_opensearch: SceneSearchClient):
        self.session = session
        self.scene_opensearch = scene_opensearch
        self.settings = get_settings()

    async def search(
        self,
        query: str,
        org_id: UUID,
        alpha: float,
        filters: SearchFilters,
    ) -> SceneSearchResponse:
        logger.info(
            "scene_search_started",
            org_id=str(org_id),
            query=query[:50],
            alpha=alpha,
        )

        filter_dict = {
            "date_from": filters.date_from,
            "date_to": filters.date_to,
            "source_types": filters.source_types,
            "library_ids": filters.library_ids,
            "person_cluster_ids": filters.person_cluster_ids,
            "keyword_tags_in": filters.keyword_tags_in,
            "keyword_tags_not_in": filters.keyword_tags_not_in,
            "product_tags_in": filters.product_tags_in,
            "product_tags_not_in": filters.product_tags_not_in,
            "product_entities_in": filters.product_entities_in,
            "product_entities_not_in": filters.product_entities_not_in,
        }

        query_embedding = await get_query_embedding(query)

        lexical_results = await self.scene_opensearch.search_lexical(
            query=query,
            org_id=str(org_id),
            filters=filter_dict,
            size=self.settings.search_lexical_top_k,
        )

        vector_results = await self.scene_opensearch.search_vector(
            embedding=query_embedding,
            org_id=str(org_id),
            filters=filter_dict,
            size=self.settings.search_vector_top_k,
        )

        # Reuse the exact same RRF fusion math as segment search
        ranked_items = compute_weighted_rrf(lexical_results, vector_results, alpha)

        diversified = diversify_results(
            ranked_items,
            max_per_video=self.settings.search_max_scenes_per_video,
            target_count=self.settings.search_page_size,
        )

        # Enrich with library names and people labels
        library_repo = LibraryRepository(self.session)
        libraries = await library_repo.list_by_org(org_id)
        library_map = {str(lib.id): lib.name for lib in libraries}

        people_repo = PeopleClusterLabelRepository(self.session)
        people_labels = await people_repo.list_by_org(org_id)
        people_label_map = {p.person_cluster_id: p.label for p in people_labels}

        results: list[SceneResult] = []
        for item in diversified:
             src = item.source
             results.append(
                 SceneResult(
                     scene_id=src.get("scene_id", item.doc_id),
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
                     speech_segment_count=src.get("speech_segment_count", 0),
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

        facet_data = await self.scene_opensearch.get_facets(str(org_id), filter_dict)

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
            "scene_search_completed",
            org_id=str(org_id),
            result_count=len(results),
            total_candidates=len(ranked_items),
        )

        return SceneSearchResponse(
            results=results,
            total_candidates=len(ranked_items),
            facets=facets,
            query=query,
            alpha=alpha,
        )
