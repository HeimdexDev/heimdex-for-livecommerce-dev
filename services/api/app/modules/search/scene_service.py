"""
Scene search service.

Orchestrates three search modes over the scenes index:
- **metadata**: BM25 on video title / source path (file-level search)
- **lexical**: BM25 on transcript, OCR, caption, title (content search)
- **semantic**: 3-way weighted RRF fusion (text kNN + visual kNN + BM25)

The public ``search()`` method routes to the appropriate internal method
based on ``search_mode``. Shared logic (people matching, filter building,
result construction, facets, video grouping) is extracted into reusable
helpers to avoid duplication across modes.

Visual search (SigLIP2 kNN) is semantic-mode-only, gated by both the
``visual_embedding_enabled`` setting and per-query intent classification.
Metadata and lexical modes are pure BM25 — no embeddings, no kNN.
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
from app.modules.drive.repository import DriveFileRepository
from app.modules.people.repository import (
    PeopleClusterLabelRepository,
    PeopleExcludePreferenceRepository,
    PeopleVideoExclusionRepository,
)
from app.modules.search.embedding import get_query_embedding
from app.modules.search.visual_embedding import get_visual_query_embedding
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

        ranked_items = compute_weighted_rrf(
            metadata_results, [], [],
            bm25_weight=1.0, text_knn_weight=0.0, visual_weight=0.0,
        )

        diversified = diversify_results(
            ranked_items,
            max_per_video=self.settings.search_max_scenes_per_video,
            target_count=self.settings.search_page_size,
            content_types=ctx.filter_dict.get("content_types"),
        )

        results = self._build_scene_results(diversified, ctx.library_map)
        facets = self._build_facets(ctx.facet_data, ctx.library_map, ctx.people_label_map)
        await self._backfill_web_view_links(results, ctx.org_id)

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

        ranked_items = compute_weighted_rrf(
            lexical_results, [], [],
            bm25_weight=1.0, text_knn_weight=0.0, visual_weight=0.0,
        )

        diversified = diversify_results(
            ranked_items,
            max_per_video=self.settings.search_max_scenes_per_video,
            target_count=self.settings.search_page_size,
            content_types=ctx.filter_dict.get("content_types"),
        )

        results = self._build_scene_results(diversified, ctx.library_map)
        facets = self._build_facets(ctx.facet_data, ctx.library_map, ctx.people_label_map)
        await self._backfill_web_view_links(results, ctx.org_id)

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
    # Mode: semantic  (3-way weighted RRF: text kNN + visual kNN + BM25)
    # ------------------------------------------------------------------
    async def _search_semantic(
        self,
        ctx: _SearchContext,
        alpha: float,
    ) -> SceneSearchResponse | VideoSearchResponse:
        """Semantic mode: meaning-based search via 3-way weighted RRF.

        Uses intent classification to determine per-signal weights:
        - BM25 (lexical): exact Korean term matching on transcript/OCR/caption
        - Text kNN (E5): semantic meaning via text embeddings
        - Visual kNN (SigLIP2): visual similarity via cross-modal embeddings

        Visual kNN is gated by ``visual_embedding_enabled``.  When disabled,
        the visual weight is redistributed proportionally to BM25 and text kNN
        so search behaviour degrades gracefully.

        All embedding generation and OpenSearch queries run in parallel via
        ``asyncio.gather()`` for minimal latency overhead.
        """
        intent = classify_intent(ctx.query)
        settings = self.settings

        # --- Determine effective 3-way weights ---
        visual_enabled = settings.visual_embedding_enabled

        if visual_enabled and intent.visual_weight > 0:
            bm25_w = intent.bm25_weight
            text_w = intent.text_knn_weight
            vis_w = intent.visual_weight
        else:
            # Redistribute visual weight proportionally to BM25 + text kNN
            remaining = intent.bm25_weight + intent.text_knn_weight
            if remaining > 0:
                bm25_w = intent.bm25_weight / remaining
                text_w = intent.text_knn_weight / remaining
            else:
                bm25_w = 0.5
                text_w = 0.5
            vis_w = 0.0

        logger.info(
            "semantic_search_with_intent",
            query=ctx.query[:50],
            intent_type=intent.intent_type,
            visual_enabled=visual_enabled,
            bm25_weight=round(bm25_w, 3),
            text_knn_weight=round(text_w, 3),
            visual_weight=round(vis_w, 3),
            matched_patterns=intent.matched_patterns,
        )

        # --- Generate embeddings in parallel ---
        embed_coros: list[Any] = [get_query_embedding(ctx.query)]
        if vis_w > 0:
            embed_coros.append(get_visual_query_embedding(ctx.query))

        embed_results = await asyncio.gather(*embed_coros)
        query_embedding = embed_results[0]
        visual_embedding = embed_results[1] if len(embed_results) > 1 else None

        # --- Dispatch OpenSearch queries in parallel (intent-gated) ---
        search_coros: list[Any] = []
        search_keys: list[str] = []

        # Text kNN — always runs in semantic mode
        search_keys.append("text_knn")
        search_coros.append(
            self.scene_opensearch.search_vector(
                embedding=query_embedding,
                org_id=ctx.org_id_str,
                filters=ctx.filter_dict,
                size=settings.search_vector_top_k,
            )
        )

        # Visual kNN — only when weight > 0 and embedding available
        if vis_w > 0 and visual_embedding is not None:
            search_keys.append("visual_knn")
            search_coros.append(
                self.scene_opensearch.search_visual_vector(
                    visual_embedding=visual_embedding,
                    org_id=ctx.org_id_str,
                    filters=ctx.filter_dict,
                    size=settings.search_vector_top_k,
                )
            )

        # BM25 — only when weight > 0
        if bm25_w > 0:
            search_keys.append("bm25")
            search_coros.append(
                self.scene_opensearch.search_lexical(
                    query=ctx.query,
                    org_id=ctx.org_id_str,
                    filters=ctx.filter_dict,
                    size=settings.search_lexical_top_k,
                    include_ocr=ctx.include_ocr,
                    matched_person_cluster_ids=ctx.matched_person_cluster_ids or None,
                )
            )

        search_results = await asyncio.gather(*search_coros)
        result_map = dict(zip(search_keys, search_results))

        vector_results = result_map["text_knn"]
        visual_results = result_map.get("visual_knn", [])
        lexical_results = result_map.get("bm25", [])

        # --- 3-way weighted RRF fusion ---
        ranked_items = compute_weighted_rrf(
            lexical_results=lexical_results,
            vector_results=vector_results,
            visual_results=visual_results,
            bm25_weight=bm25_w,
            text_knn_weight=text_w,
            visual_weight=vis_w,
        )

        diversified = diversify_results(
            ranked_items,
            max_per_video=settings.search_max_scenes_per_video,
            target_count=settings.search_page_size,
            content_types=ctx.filter_dict.get("content_types"),
        )

        results = self._build_scene_results(diversified, ctx.library_map)
        facets = self._build_facets(ctx.facet_data, ctx.library_map, ctx.people_label_map)
        await self._backfill_web_view_links(results, ctx.org_id)

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

        # Per-video exclusions
        video_exclusion_pairs: list[tuple[str, str]] = []
        if user_id is not None:
            video_excl_repo = PeopleVideoExclusionRepository(self.session)
            video_exclusion_pairs = await video_excl_repo.list_by_user(org_id, user_id)

        matched_person_cluster_ids: list[str] = []
        for p in people_labels:
            if p.label and p.label.strip() and p.label.strip() in query:
                matched_person_cluster_ids.append(p.person_cluster_id)

        effective_person_ids = list(filters.person_cluster_ids or [])
        if matched_person_cluster_ids:
            effective_person_ids = list(set(effective_person_ids + matched_person_cluster_ids))
            # When a person name is detected in the query, remove that person
            # from global exclusions to prevent contradictory OpenSearch clauses
            # (filter MUST include person + must_not MUST exclude person → 0 results).
            matched_set = set(matched_person_cluster_ids)
            excluded_before = len(exclude_ids_not_in)
            exclude_ids_not_in = [
                pid for pid in exclude_ids_not_in if pid not in matched_set
            ]
            if len(exclude_ids_not_in) < excluded_before:
                logger.info(
                    "person_name_override_global_exclude",
                    query=query[:50],
                    overridden_ids=[pid for pid in matched_set if pid not in set(exclude_ids_not_in)],
                    remaining_excludes=len(exclude_ids_not_in),
                )
            logger.info(
                "person_name_detected_in_query",
                query=query[:50],
                matched_labels=[people_label_map.get(pid) for pid in matched_person_cluster_ids],
                matched_cluster_ids=matched_person_cluster_ids,
            )

        filter_dict: dict[str, Any] = {
            "date_from": filters.date_from,
            "date_to": filters.date_to,
            "content_types": filters.content_types,
            "source_types": filters.source_types,
            "library_ids": filters.library_ids,
            "person_cluster_ids": effective_person_ids or None,
            "person_cluster_ids_not_in": exclude_ids_not_in or None,
            "person_video_exclusions": video_exclusion_pairs or None,
            "keyword_tags_in": filters.keyword_tags_in,
            "keyword_tags_not_in": filters.keyword_tags_not_in,
            "product_tags_in": filters.product_tags_in,
            "product_tags_not_in": filters.product_tags_not_in,
            "product_entities_in": filters.product_entities_in,
            "product_entities_not_in": filters.product_entities_not_in,
        }

        org_id_str = str(org_id)

        library_repo = LibraryRepository(self.session)
        libraries, facet_data = await asyncio.gather(
            library_repo.list_by_org(org_id),
            self.scene_opensearch.get_facets(org_id_str, filter_dict),
        )
        library_map = {str(lib.id): lib.name for lib in libraries}

        if filters.library_ids:
            requested = {str(lid) for lid in filters.library_ids}
            unknown = requested - set(library_map.keys())
            if unknown:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown library_ids: {sorted(unknown)}",
                )

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

    async def _backfill_web_view_links(
        self, results: list[SceneResult], org_id: UUID,
    ) -> None:
        """Backfill web_view_link from Postgres for Drive scenes missing it in OpenSearch.

        Mutates the results list in-place. Only queries Postgres when there are
        Drive video IDs (prefix 'gd_') with missing web_view_link.
        """
        missing_ids = list({
            r.video_id for r in results
            if not r.web_view_link and r.video_id.startswith("gd_")
        })
        if not missing_ids:
            return
        drive_repo = DriveFileRepository(self.session)
        link_map = await drive_repo.get_web_view_links(org_id, missing_ids)
        for r in results:
            if not r.web_view_link and r.video_id in link_map:
                r.web_view_link = link_map[r.video_id]

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
                    speaker_transcript=src.get("speaker_transcript", "")[:500],
                    speaker_count=src.get("speaker_count", 0),
                    keyframe_timestamp_ms=src.get("keyframe_timestamp_ms", 0),
                    content_type=src.get("content_type", "video"),
                    image_width=src.get("image_width"),
                    image_height=src.get("image_height"),
                    image_orientation=src.get("image_orientation"),
                    debug=DebugInfo(
                        lexical_rank=item.lexical_rank,
                        lexical_score=item.lexical_score,
                        vector_rank=item.vector_rank,
                        vector_score=item.vector_score,
                        visual_rank=item.visual_rank,
                        visual_score=item.visual_score,
                        lexical_contribution=item.lexical_contribution,
                        vector_contribution=item.vector_contribution,
                        visual_contribution=item.visual_contribution,
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
            content_types=[
                FacetItem(
                    value=bucket["key"],
                    count=bucket["doc_count"],
                    label=bucket["key"],
                )
                for bucket in facet_data.get("content_types", [])
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
