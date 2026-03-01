"""
Scene search service.

Orchestrates three search modes over the scenes index:
- **metadata**: BM25 on video title / source path (file-level search)
- **lexical**: BM25 on transcript, OCR, caption, title (content search)
- **semantic**: KNN vector search on embedding_vector (meaning search)

The public ``search()`` method routes to the appropriate internal method
based on ``search_mode``. Shared logic (people matching, filter building,
result construction, facets, video grouping) is extracted into reusable
helpers to avoid duplication across modes.
"""
import asyncio
import html
from typing import Any, Literal
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
from app.modules.search.embedding import get_query_embedding
from app.modules.search.fusion import compute_weighted_rrf, diversify_results
from app.modules.search.intent import classify_intent
from app.modules.search.scene_client import SceneSearchClient
from app.modules.search.schemas import (
    DebugInfo,
    Facets,
    FacetItem,
    SceneResult,
    SceneSearchResponse,
    SearchFilters,
    VideoResult,
    VideoSearchResponse,
)

logger = get_logger(__name__)


class _SearchContext:
    """Shared pre-computed data for all search modes.

    Built once per ``search()`` call by ``_prepare_search_context()``.
    """

    __slots__ = (
        "query", "org_id", "org_id_str", "filter_dict",
        "matched_person_cluster_ids", "people_label_map",
        "library_map", "facet_data", "include_ocr", "group_by",
    )

    def __init__(
        self,
        query: str,
        org_id: UUID,
        org_id_str: str,
        filter_dict: dict[str, Any],
        matched_person_cluster_ids: list[str],
        people_label_map: dict[str, str | None],
        library_map: dict[str, str],
        facet_data: dict[str, list[dict[str, Any]]],
        include_ocr: bool | None,
        group_by: str,
    ):
        self.query = query
        self.org_id = org_id
        self.org_id_str = org_id_str
        self.filter_dict = filter_dict
        self.matched_person_cluster_ids = matched_person_cluster_ids
        self.people_label_map = people_label_map
        self.library_map = library_map
        self.facet_data = facet_data
        self.include_ocr = include_ocr
        self.group_by = group_by


class SceneSearchService:
    """Search service for the scenes index.

    Routes to mode-specific implementations via ``search()``.
    """

    def __init__(self, session: AsyncSession, scene_opensearch: SceneSearchClient):
        self.session = session
        self.scene_opensearch = scene_opensearch
        self.settings = get_settings()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    async def search(
        self,
        query: str,
        org_id: UUID,
        alpha: float,
        filters: SearchFilters,
        include_ocr: bool | None = None,
        user_id: UUID | None = None,
        group_by: str = "scene",
        search_mode: Literal["metadata", "lexical", "semantic"] = "lexical",
    ) -> SceneSearchResponse | VideoSearchResponse:
        """Route to mode-specific search implementation.

        When ``search_mode`` is provided it takes precedence over ``alpha``.
        Legacy callers that only send ``alpha`` default to ``"lexical"`` mode
        which preserves the previous hybrid behaviour.
        """
        logger.info(
            "scene_search_started",
            org_id=str(org_id),
            query=query[:50],
            alpha=alpha,
            search_mode=search_mode,
        )

        ctx = await self._prepare_search_context(
            query=query,
            org_id=org_id,
            filters=filters,
            include_ocr=include_ocr,
            user_id=user_id,
            group_by=group_by,
        )

        match search_mode:
            case "metadata":
                return await self._search_metadata(ctx, alpha)
            case "semantic":
                return await self._search_semantic(ctx, alpha)
            case _:
                # Default + explicit "lexical"
                return await self._search_lexical(ctx, alpha)

    # ------------------------------------------------------------------
    # Mode: metadata  (BM25 on video title / source path only)
    # ------------------------------------------------------------------
    async def _search_metadata(
        self,
        ctx: _SearchContext,
        alpha: float,
    ) -> SceneSearchResponse | VideoSearchResponse:
        """Metadata mode: search video filename / source path.

        No embedding computation, no transcript/OCR/caption matching.
        Always groups by video (metadata is file-level).
        """
        metadata_results = await self.scene_opensearch.search_metadata(
            query=ctx.query,
            org_id=ctx.org_id_str,
            filters=ctx.filter_dict,
            size=self.settings.search_lexical_top_k,
        )

        # Build ranked items using RRF with alpha=0 (pure lexical)
        ranked_items = compute_weighted_rrf(metadata_results, [], 0.0)

        diversified = diversify_results(
            ranked_items,
            max_per_video=self.settings.search_max_scenes_per_video,
            target_count=self.settings.search_page_size,
        )

        results = self._build_scene_results(diversified, ctx.library_map)
        facets = self._build_facets(ctx.facet_data, ctx.library_map, ctx.people_label_map)

        # Metadata mode always returns video-grouped results
        return self._group_by_video(
            results=results,
            ranked_items=ranked_items,
            facets=facets,
            query=ctx.query,
            alpha=alpha,
            org_id=ctx.org_id,
        )

    # ------------------------------------------------------------------
    # Mode: lexical  (BM25 on all content fields — no embedding)
    # ------------------------------------------------------------------
    async def _search_lexical(
        self,
        ctx: _SearchContext,
        alpha: float,
    ) -> SceneSearchResponse | VideoSearchResponse:
        """Lexical mode: exact word matching on transcript, OCR, caption, title.

        No embedding computation — saves ~800ms latency. Uses existing
        ``search_lexical()`` client method with ``alpha=0.0``.
        """
        lexical_results = await self.scene_opensearch.search_lexical(
            query=ctx.query,
            org_id=ctx.org_id_str,
            filters=ctx.filter_dict,
            size=self.settings.search_lexical_top_k,
            include_ocr=ctx.include_ocr,
            matched_person_cluster_ids=ctx.matched_person_cluster_ids or None,
        )

        ranked_items = compute_weighted_rrf(lexical_results, [], 0.0)

        diversified = diversify_results(
            ranked_items,
            max_per_video=self.settings.search_max_scenes_per_video,
            target_count=self.settings.search_page_size,
        )

        results = self._build_scene_results(diversified, ctx.library_map)
        facets = self._build_facets(ctx.facet_data, ctx.library_map, ctx.people_label_map)

        return self._maybe_group_by_video(
            results=results,
            ranked_items=ranked_items,
            facets=facets,
            query=ctx.query,
            alpha=alpha,
            org_id=ctx.org_id,
            group_by=ctx.group_by,
        )

    # ------------------------------------------------------------------
    # Mode: semantic  (intent-aware hybrid: kNN + optional BM25)
    # ------------------------------------------------------------------
    async def _search_semantic(
        self,
        ctx: _SearchContext,
        alpha: float,
    ) -> SceneSearchResponse | VideoSearchResponse:
        """Semantic mode: meaning-based search via embedding vector.

        Uses intent classification to intelligently blend BM25 when the
        query contains metadata/factual signals. Pure kNN queries (general/
        visual intent) run without BM25 overhead.
        """
        intent = classify_intent(ctx.query)

        # Intent-determined alpha overrides the fixed 1.0 when BM25 is beneficial
        effective_alpha = intent.alpha if intent.intent_type != "general" else alpha

        logger.info(
            "semantic_search_with_intent",
            query=ctx.query[:50],
            intent_type=intent.intent_type,
            effective_alpha=effective_alpha,
            matched_patterns=intent.matched_patterns,
        )

        # Always run kNN
        query_embedding = await get_query_embedding(ctx.query)

        vector_results = await self.scene_opensearch.search_vector(
            embedding=query_embedding,
            org_id=ctx.org_id_str,
            filters=ctx.filter_dict,
            size=self.settings.search_vector_top_k,
        )

        # Run BM25 when intent suggests lexical signals are valuable
        lexical_results: list[dict[str, Any]] = []
        if effective_alpha < 1.0:
            lexical_results = await self.scene_opensearch.search_lexical(
                query=ctx.query,
                org_id=ctx.org_id_str,
                filters=ctx.filter_dict,
                size=self.settings.search_lexical_top_k,
                include_ocr=ctx.include_ocr,
                matched_person_cluster_ids=ctx.matched_person_cluster_ids or None,
            )

        ranked_items = compute_weighted_rrf(lexical_results, vector_results, effective_alpha)

        diversified = diversify_results(
            ranked_items,
            max_per_video=self.settings.search_max_scenes_per_video,
            target_count=self.settings.search_page_size,
        )

        results = self._build_scene_results(diversified, ctx.library_map)
        facets = self._build_facets(ctx.facet_data, ctx.library_map, ctx.people_label_map)

        return self._maybe_group_by_video(
            results=results,
            ranked_items=ranked_items,
            facets=facets,
            query=ctx.query,
            alpha=effective_alpha,
            org_id=ctx.org_id,
            group_by=ctx.group_by,
        )
    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------
    async def _prepare_search_context(
        self,
        query: str,
        org_id: UUID,
        filters: SearchFilters,
        include_ocr: bool | None,
        user_id: UUID | None,
        group_by: str,
    ) -> _SearchContext:
        """Build the shared context used by all search modes.

        Runs people-matching, filter construction, library lookup, and
        facet aggregation. Postgres queries are sequential (single
        AsyncSession), but facets run on OpenSearch concurrently after
        filter_dict is built.
        """
        people_repo = PeopleClusterLabelRepository(self.session)
        people_labels = await people_repo.list_by_org(org_id)
        people_label_map: dict[str, str | None] = {
            p.person_cluster_id: p.label for p in people_labels
        }

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

        filter_dict: dict[str, Any] = {
            "date_from": filters.date_from,
            "date_to": filters.date_to,
            "source_types": filters.source_types,
            "library_ids": filters.library_ids,
            "person_cluster_ids": effective_person_ids or None,
            "person_cluster_ids_not_in": exclude_ids_not_in or None,
            "keyword_tags_in": filters.keyword_tags_in,
            "keyword_tags_not_in": filters.keyword_tags_not_in,
            "product_tags_in": filters.product_tags_in,
            "product_tags_not_in": filters.product_tags_not_in,
            "product_entities_in": filters.product_entities_in,
            "product_entities_not_in": filters.product_entities_not_in,
        }

        org_id_str = str(org_id)

        # Facets + library lookup can run concurrently with each other
        # (facets go to OpenSearch, libraries go to Postgres).
        # BUT AsyncSession doesn't support concurrent ops, so we do them sequentially.
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

        facet_data = await self.scene_opensearch.get_facets(org_id_str, filter_dict)

        return _SearchContext(
            query=query,
            org_id=org_id,
            org_id_str=org_id_str,
            filter_dict=filter_dict,
            matched_person_cluster_ids=matched_person_cluster_ids,
            people_label_map=people_label_map,
            library_map=library_map,
            facet_data=facet_data,
            include_ocr=include_ocr,
            group_by=group_by,
        )

    @staticmethod
    def _build_scene_results(
        diversified: list[Any],
        library_map: dict[str, str],
    ) -> list[SceneResult]:
        """Convert diversified RankedItems into SceneResult DTOs."""
        results: list[SceneResult] = []
        for item in diversified:
            src = item.source
            ocr_raw = src.get("ocr_text_raw", "") or ""
            ocr_snippet = html.escape(ocr_raw[:200]) if ocr_raw else ""
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
                    ocr_snippet=ocr_snippet,
                    scene_caption=src.get("scene_caption", "")[:200],
                    thumbnail_url=src.get("thumbnail_url"),
                    source_type=src.get("source_type", "gdrive"),
                    web_view_link=src.get("web_view_link"),
                    required_drive_nickname=src.get("required_drive_nickname"),
                    capture_time=src.get("capture_time"),
                    people_cluster_ids=src.get("people_cluster_ids", []),
                    speech_segment_count=src.get("speech_segment_count", 0),
                    ocr_char_count=src.get("ocr_char_count", 0),
                    keyframe_timestamp_ms=src.get("keyframe_timestamp_ms", 0),
                    debug=DebugInfo(
                        lexical_rank=item.lexical_rank,
                        lexical_score=item.lexical_score,
                        vector_rank=item.vector_rank,
                        vector_score=item.vector_score,
                        lexical_contribution=item.lexical_contribution,
                        vector_contribution=item.vector_contribution,
                        ocr_contribution=0.0,
                        fused_score=item.fused_score,
                        quality_factor=item.quality_factor,
                        adjusted_score=item.adjusted_score,
                        diversification_penalty=item.diversification_penalty,
                    ),
                )
            )
        return results

    @staticmethod
    def _build_facets(
        facet_data: dict[str, list[dict[str, Any]]],
        library_map: dict[str, str],
        people_label_map: dict[str, str | None],
    ) -> Facets:
        """Build Facets DTO from raw OpenSearch aggregation buckets."""
        return Facets(
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

    @staticmethod
    def _group_by_video(
        results: list[SceneResult],
        ranked_items: list[Any],
        facets: Facets,
        query: str,
        alpha: float,
        org_id: UUID,
    ) -> VideoSearchResponse:
        """Group scene results by video — always returns VideoSearchResponse."""
        video_groups: dict[str, list[SceneResult]] = {}
        for scene in results:
            video_groups.setdefault(scene.video_id, []).append(scene)

        video_results: list[VideoResult] = []
        for vid, scenes in video_groups.items():
            best = scenes[0]
            video_results.append(
                VideoResult(
                    video_id=vid,
                    video_title=best.video_title,
                    library_id=best.library_id,
                    library_name=best.library_name,
                    source_type=best.source_type,
                    web_view_link=best.web_view_link,
                    matching_scene_count=len(scenes),
                    best_scene=best,
                    score=best.debug.adjusted_score,
                )
            )
        video_results.sort(key=lambda v: v.score, reverse=True)

        unique_video_count = len(set(item.video_id for item in ranked_items))

        logger.info(
            "video_search_completed",
            org_id=str(org_id),
            result_count=len(video_results),
            total_candidates=unique_video_count,
        )

        return VideoSearchResponse(
            results=video_results,
            total_candidates=unique_video_count,
            facets=facets,
            query=query,
            alpha=alpha,
        )

    @staticmethod
    def _maybe_group_by_video(
        results: list[SceneResult],
        ranked_items: list[Any],
        facets: Facets,
        query: str,
        alpha: float,
        org_id: UUID,
        group_by: str,
    ) -> SceneSearchResponse | VideoSearchResponse:
        """Return video-grouped or scene-level response based on group_by."""
        if group_by == "video":
            return SceneSearchService._group_by_video(
                results=results,
                ranked_items=ranked_items,
                facets=facets,
                query=query,
                alpha=alpha,
                org_id=org_id,
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
