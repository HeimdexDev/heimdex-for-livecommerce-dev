"""
Scene OpenSearch client for the heimdex_scenes index.

Manages a separate index for scene documents (parallel to the segment index).
Follows the same versioning/alias pattern as OpenSearchClient.

Scene documents contain aggregated transcript from multiple speech segments,
a single E5 embedding per scene, and scene-level metadata.
"""
from typing import Any

from opensearchpy import AsyncOpenSearch
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.logging_config import get_logger
from app.modules.search.client import get_opensearch_client

logger = get_logger(__name__)


class SceneSearchClient:
    """OpenSearch client for the scenes index.

    Index naming convention:
      - alias: ``{prefix}_scenes``  (e.g. ``heimdex_scenes``)
      - physical: ``{prefix}_scenes_{INDEX_VERSION}``  (e.g. ``heimdex_scenes_v1``)

    The mapping mirrors the segment index for fields they share (org_id,
    video_id, transcript_*, embedding_vector, people_cluster_ids) and adds
    scene-specific fields (scene_id, thumbnail_url, speech_segment_count).
    """

    EMBEDDING_DIMENSION = 1024
    INDEX_VERSION = "v1"

    def __init__(self) -> None:
        self.settings = get_settings()
        self.client: AsyncOpenSearch = get_opensearch_client()
        self.alias_name = f"{self.settings.opensearch_index_prefix}_scenes"
        self.index_name = f"{self.alias_name}_{self.INDEX_VERSION}"

    async def close(self) -> None:
        await self.client.close()

    # ------------------------------------------------------------------
    # Nori detection (shared logic with segment client)
    # ------------------------------------------------------------------
    async def _check_nori_available(self) -> bool:
        """Check if the Nori analyzer plugin is installed."""
        try:
            response = await self.client.cat.plugins(format="json")
            plugins = [p.get("component", "") for p in response]
            nori_installed = any("analysis-nori" in p for p in plugins)
            logger.info("scene_nori_plugin_check", installed=nori_installed)
            return nori_installed
        except Exception as e:
            logger.warning("scene_nori_plugin_check_failed", error=str(e))
            return False

    # ------------------------------------------------------------------
    # Index lifecycle
    # ------------------------------------------------------------------
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def ensure_index_exists(self) -> dict[str, Any]:
        """Create the scenes index + alias if missing.

        SAFETY: Does NOT auto-flip alias on version mismatch.
        Use ``promote_alias_to_current_version()`` for explicit promotion.
        """
        result: dict[str, Any] = {
            "index_name": self.index_name,
            "alias_name": self.alias_name,
            "index_created": False,
            "alias_created": False,
            "alias_mismatch_warning": None,
        }

        index_exists = await self.client.indices.exists(index=self.index_name)

        if not index_exists:
            await self.create_index()
            result["index_created"] = True
            result["alias_created"] = True
            logger.info(
                "scene_index_and_alias_created",
                index=self.index_name,
                alias=self.alias_name,
            )
        else:
            alias_targets = await self.get_alias_targets()

            if not alias_targets:
                await self.client.indices.put_alias(
                    index=self.index_name,
                    name=self.alias_name,
                )
                result["alias_created"] = True
                logger.info(
                    "scene_alias_created_for_existing_index",
                    alias=self.alias_name,
                    index=self.index_name,
                )
            elif self.index_name not in alias_targets:
                warning_msg = (
                    f"ALIAS MISMATCH DETECTED: Alias '{self.alias_name}' exists but points to "
                    f"{alias_targets}, not '{self.index_name}'. "
                    f"Run promote_alias_to_current_version() to explicitly promote."
                )
                result["alias_mismatch_warning"] = warning_msg
                result["alias_current_targets"] = alias_targets
                logger.warning(
                    "scene_alias_mismatch_detected",
                    alias=self.alias_name,
                    expected_index=self.index_name,
                    actual_targets=alias_targets,
                )
            else:
                logger.debug(
                    "scene_index_and_alias_already_configured",
                    index=self.index_name,
                    alias=self.alias_name,
                )

        return result

    async def create_index(self) -> None:
        """Create the scenes physical index with Nori (when available) and kNN."""
        nori_available = await self._check_nori_available()

        settings: dict[str, Any] = {
            "index": {
                "number_of_shards": 1,
                "number_of_replicas": 0,
                "knn": True,
                "knn.algo_param.ef_search": 100,
            },
            "analysis": {
                "tokenizer": {
                    "korean_tokenizer": {
                        "type": "nori_tokenizer",
                        "decompound_mode": "mixed",
                        "discard_punctuation": False,
                    },
                } if nori_available else {},
                "filter": {
                    "korean_pos_filter": {
                        "type": "nori_part_of_speech",
                        "stoptags": [
                            "E", "IC", "J", "MAG", "MAJ", "MM",
                            "SP", "SSC", "SSO", "SC", "SE",
                            "XPN", "XSA", "XSN", "XSV",
                            "UNA", "NA", "VSV",
                        ],
                    },
                } if nori_available else {},
                "analyzer": {
                    **({"korean_analyzer": {
                        "type": "custom",
                        "tokenizer": "korean_tokenizer",
                        "filter": ["lowercase", "korean_pos_filter", "nori_readingform"],
                    }} if nori_available else {}),
                    "fallback_analyzer": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": ["lowercase", "asciifolding"],
                    },
                },
            },
        }

        transcript_analyzer = "korean_analyzer" if nori_available else "fallback_analyzer"
        logger.info(
            "scene_index_analyzer_selected",
            analyzer=transcript_analyzer,
            nori_available=nori_available,
        )

        mappings: dict[str, Any] = {
            "properties": {
                # Tenancy / ownership
                "org_id": {"type": "keyword"},
                "library_id": {"type": "keyword"},
                "video_id": {"type": "keyword"},
                # Scene identity
                "scene_id": {"type": "keyword"},
                # Temporal
                "start_ms": {"type": "integer"},
                "end_ms": {"type": "integer"},
                # Transcript
                "transcript_raw": {"type": "text"},
                "transcript_norm": {
                    "type": "text",
                    "analyzer": transcript_analyzer,
                    "search_analyzer": transcript_analyzer,
                },
                "transcript_char_count": {"type": "integer"},
                # Embedding
                "embedding_vector": {
                    "type": "knn_vector",
                    "dimension": self.EMBEDDING_DIMENSION,
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "lucene",
                        "parameters": {"ef_construction": 128, "m": 24},
                    },
                },
                # People
                "people_cluster_ids": {"type": "keyword"},
                # Scene metadata
                "speech_segment_count": {"type": "integer"},
                "thumbnail_url": {"type": "keyword", "index": False},
                # Source metadata (denormalized for filtering)
                "source_type": {"type": "keyword"},
                "required_drive_nickname": {"type": "keyword"},
                "capture_time": {"type": "date"},
                "ingest_time": {"type": "date"},
            }
        }

        logger.info(
            "creating_scene_opensearch_index",
            index=self.index_name,
            alias=self.alias_name,
        )

        try:
            await self.client.indices.create(
                index=self.index_name,
                body={
                    "settings": settings,
                    "mappings": mappings,
                    "aliases": {
                        self.alias_name: {},
                    },
                },
            )
            logger.info(
                "scene_opensearch_index_created",
                index=self.index_name,
                alias=self.alias_name,
                dimension=self.EMBEDDING_DIMENSION,
            )
        except Exception as e:
            if "resource_already_exists_exception" not in str(e).lower():
                raise
            logger.info("scene_opensearch_index_already_exists", index=self.index_name)

    # ------------------------------------------------------------------
    # Alias helpers
    # ------------------------------------------------------------------
    async def get_alias_targets(self, alias_name: str | None = None) -> list[str]:
        """Return list of indices the alias currently points to."""
        alias = alias_name or self.alias_name
        try:
            alias_info = await self.client.indices.get_alias(name=alias)
            return list(alias_info.keys())
        except Exception as e:
            if "alias" in str(e).lower() and "not" in str(e).lower():
                return []
            logger.warning("scene_get_alias_targets_failed", alias=alias, error=str(e))
            return []

    async def promote_alias_to_current_version(self) -> dict[str, Any]:
        """Atomically swap alias to the current versioned index."""
        before_targets = await self.get_alias_targets()

        index_exists = await self.client.indices.exists(index=self.index_name)
        if not index_exists:
            raise ValueError(
                f"Cannot promote alias: target index '{self.index_name}' does not exist. "
                f"Run ensure_index_exists() first."
            )

        if before_targets == [self.index_name]:
            logger.info(
                "scene_alias_already_current",
                alias=self.alias_name,
                index=self.index_name,
            )
            return {
                "success": True,
                "already_current": True,
                "alias": self.alias_name,
                "before_targets": before_targets,
                "after_targets": before_targets,
            }

        logger.info(
            "promoting_scene_alias",
            alias=self.alias_name,
            from_indices=before_targets,
            to_index=self.index_name,
        )

        await self.client.indices.update_aliases(
            body={
                "actions": [
                    {"remove": {"index": "*", "alias": self.alias_name}},
                    {"add": {"index": self.index_name, "alias": self.alias_name}},
                ]
            }
        )

        after_targets = await self.get_alias_targets()

        logger.info(
            "scene_alias_promoted",
            alias=self.alias_name,
            before_targets=before_targets,
            after_targets=after_targets,
        )

        return {
            "success": True,
            "already_current": False,
            "alias": self.alias_name,
            "before_targets": before_targets,
            "after_targets": after_targets,
        }

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------
    async def index_scene(self, doc_id: str, document: dict[str, Any]) -> None:
        """Index a single scene document."""
        await self.client.index(
            index=self.index_name,
            id=doc_id,
            body=document,
            refresh=True,
        )

    async def bulk_index_scenes(self, documents: list[tuple[str, dict[str, Any]]]) -> None:
        """Bulk-index scene documents.

        Args:
            documents: List of ``(scene_id, document_dict)`` tuples.
        """
        if not documents:
            return

        actions: list[dict[str, Any]] = []
        for doc_id, doc in documents:
            actions.append({"index": {"_index": self.index_name, "_id": doc_id}})
            actions.append(doc)

        await self.client.bulk(body=actions, refresh=True)
        logger.info("scene_bulk_indexed_documents", count=len(documents))

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    async def search_lexical(
        self,
        query: str,
        org_id: str,
        filters: dict[str, Any],
        size: int = 200,
    ) -> list[dict[str, Any]]:
        """BM25 lexical search on scene transcripts.

        Short queries (<=3 words) get phrase-boost for precision,
        matching the segment client behaviour.
        """
        filter_clauses = self._build_filter_clauses(filters)

        match_query: dict[str, Any] = {
            "match": {
                "transcript_norm": {
                    "query": query,
                    "operator": "or",
                    "minimum_should_match": "50%",
                }
            }
        }

        query_word_count = len(query.split())

        if query_word_count <= 3:
            search_query: dict[str, Any] = {
                "bool": {
                    "must": [{"term": {"org_id": org_id}}],
                    "should": [
                        match_query,
                        {
                            "match_phrase": {
                                "transcript_norm": {
                                    "query": query,
                                    "boost": 2.0,
                                    "slop": 1,
                                }
                            }
                        },
                    ],
                    "minimum_should_match": 1,
                    "filter": filter_clauses,
                }
            }
        else:
            search_query = {
                "bool": {
                    "must": [
                        {"term": {"org_id": org_id}},
                        match_query,
                    ],
                    "filter": filter_clauses,
                }
            }

        body: dict[str, Any] = {
            "query": search_query,
            "size": size,
            "_source": True,
        }

        response = await self.client.search(index=self.alias_name, body=body)
        return response["hits"]["hits"]

    async def search_vector(
        self,
        embedding: list[float],
        org_id: str,
        filters: dict[str, Any],
        size: int = 200,
    ) -> list[dict[str, Any]]:
        """kNN vector search on scene embeddings."""
        filter_clauses = [{"term": {"org_id": org_id}}] + self._build_filter_clauses(filters)

        body: dict[str, Any] = {
            "query": {
                "knn": {
                    "embedding_vector": {
                        "vector": embedding,
                        "k": size,
                        "filter": {"bool": {"must": filter_clauses}},
                    }
                }
            },
            "size": size,
            "_source": True,
        }

        response = await self.client.search(index=self.alias_name, body=body)
        return response["hits"]["hits"]

    async def get_facets(
        self,
        org_id: str,
        filters: dict[str, Any],
    ) -> dict[str, list[dict[str, Any]]]:
        """Aggregations for libraries, source_types, and people."""
        filter_clauses = [{"term": {"org_id": org_id}}] + self._build_filter_clauses(filters)

        body: dict[str, Any] = {
            "query": {"bool": {"filter": filter_clauses}},
            "size": 0,
            "aggs": {
                "libraries": {"terms": {"field": "library_id", "size": 100}},
                "source_types": {"terms": {"field": "source_type", "size": 10}},
                "people": {"terms": {"field": "people_cluster_ids", "size": 100}},
            },
        }

        response = await self.client.search(index=self.alias_name, body=body)

        return {
            "libraries": response["aggregations"]["libraries"]["buckets"],
            "source_types": response["aggregations"]["source_types"]["buckets"],
            "people": response["aggregations"]["people"]["buckets"],
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _build_filter_clauses(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        """Build OpenSearch filter clauses from a filter dict."""
        clauses: list[dict[str, Any]] = []

        if filters.get("date_from") or filters.get("date_to"):
            range_clause: dict[str, Any] = {}
            if filters.get("date_from"):
                range_clause["gte"] = filters["date_from"].isoformat()
            if filters.get("date_to"):
                range_clause["lte"] = filters["date_to"].isoformat()
            clauses.append({"range": {"capture_time": range_clause}})

        if filters.get("source_types"):
            clauses.append({"terms": {"source_type": filters["source_types"]}})

        if filters.get("library_ids"):
            clauses.append({"terms": {"library_id": [str(lid) for lid in filters["library_ids"]]}})

        if filters.get("person_cluster_ids"):
            clauses.append({"terms": {"people_cluster_ids": filters["person_cluster_ids"]}})

        return clauses
