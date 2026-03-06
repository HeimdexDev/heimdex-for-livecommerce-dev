from typing import Any

from opensearchpy import AsyncOpenSearch
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)


def get_opensearch_client() -> AsyncOpenSearch:
    settings = get_settings()
    # Detect SSL from URL scheme (AWS OpenSearch Service uses HTTPS)
    is_https = settings.opensearch_url.startswith("https://")
    return AsyncOpenSearch(
        hosts=[settings.opensearch_url],
        use_ssl=is_https,
        verify_certs=is_https,
        ssl_show_warn=False,
        timeout=60,
        max_retries=3,
        retry_on_timeout=True,
        pool_maxsize=20,
    )


class OpenSearchClient:
    # multilingual-e5-large uses 1024 dimensions
    EMBEDDING_DIMENSION = 1024
    
    # Index versioning for zero-downtime migrations
    INDEX_VERSION = "v2"  # Bump this when changing mapping (e.g., embedding dimension)
    
    def __init__(self):
        self.settings = get_settings()
        self.client = get_opensearch_client()
        # Alias name used for all queries (allows zero-downtime index swaps)
        self.alias_name = f"{self.settings.opensearch_index_prefix}_segments"
        # Versioned index name for the actual index
        self.index_name = f"{self.alias_name}_{self.INDEX_VERSION}"

    async def close(self):
        await self.client.close()

    async def _check_nori_available(self) -> bool:
        """Check if Nori analyzer plugin is installed in OpenSearch."""
        try:
            response = await self.client.cat.plugins(params={"format": "json"})
            plugins = [p.get("component", "") for p in response]
            nori_installed = any("analysis-nori" in p for p in plugins)
            logger.info("nori_plugin_check", installed=nori_installed, plugins=plugins)
            return nori_installed
        except Exception as e:
            logger.warning("nori_plugin_check_failed", error=str(e))
            return False

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def ensure_index_exists(self) -> dict[str, Any]:
        """
        Ensure the versioned index exists. Creates alias only if missing.
        
        SAFETY: This method does NOT auto-flip alias if it already exists
        but points to a different index. Use promote_alias_to_current_version()
        for explicit alias promotion.
        
        Uses aliases for zero-downtime migrations:
        - alias_name: used for all queries (e.g., heimdex_segments)
        - index_name: versioned physical index (e.g., heimdex_segments_v2)
        
        Returns:
            Dict with index state and any warnings.
        """
        result: dict[str, Any] = {
            "index_name": self.index_name,
            "alias_name": self.alias_name,
            "index_created": False,
            "alias_created": False,
            "alias_mismatch_warning": None,
        }
        
        # Check if the versioned index exists
        index_exists = await self.client.indices.exists(index=self.index_name)
        
        if not index_exists:
            # Create new index (includes alias in creation)
            await self.create_index()
            result["index_created"] = True
            result["alias_created"] = True
            logger.info(
                "index_and_alias_created",
                index=self.index_name,
                alias=self.alias_name,
            )
        else:
            # Index exists - check alias state
            alias_targets = await self.get_alias_targets()
            
            if not alias_targets:
                # Alias doesn't exist - safe to create
                await self.client.indices.put_alias(
                    index=self.index_name,
                    name=self.alias_name,
                )
                result["alias_created"] = True
                logger.info(
                    "alias_created_for_existing_index",
                    alias=self.alias_name,
                    index=self.index_name,
                )
            elif self.index_name not in alias_targets:
                # ALIAS MISMATCH: alias exists but points to different index(es)
                # DO NOT auto-flip - warn loudly instead
                warning_msg = (
                    f"ALIAS MISMATCH DETECTED: Alias '{self.alias_name}' exists but points to "
                    f"{alias_targets}, not '{self.index_name}'. "
                    f"Run 'python -m app.modules.search.promote_alias' to explicitly promote."
                )
                result["alias_mismatch_warning"] = warning_msg
                result["alias_current_targets"] = alias_targets
                logger.warning(
                    "alias_mismatch_detected",
                    alias=self.alias_name,
                    expected_index=self.index_name,
                    actual_targets=alias_targets,
                    action="manual_promotion_required",
                )
            else:
                # Alias exists and points to current index - all good
                logger.debug(
                    "index_and_alias_already_configured",
                    index=self.index_name,
                    alias=self.alias_name,
                )
        
        return result

    async def create_index(self) -> None:
        # Check if Nori plugin is available for Korean analysis
        nori_available = await self._check_nori_available()
        
        settings = {
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
                        "decompound_mode": "mixed",  # Keep original + decomposed for better recall
                        "discard_punctuation": False,  # Better for mixed Korean/English
                    },
                } if nori_available else {},
                "filter": {
                    "korean_pos_filter": {
                        "type": "nori_part_of_speech",
                        "stoptags": [
                            "E",   # Verbal endings
                            "IC",  # Interjection
                            "J",   # Ending Particle
                            "MAG", # General Adverb
                            "MAJ", # Conjunctive Adverb
                            "MM",  # Determiner
                            "SP",  # Space
                            "SSC", # Closing brackets
                            "SSO", # Opening brackets
                            "SC",  # Separator
                            "SE",  # Ellipsis
                            "XPN", # Prefix
                            "XSA", # Adjective Suffix
                            "XSN", # Noun Suffix
                            "XSV", # Verb Suffix
                            "UNA", # Unknown
                            "NA",  # Unknown
                            "VSV", # Unknown
                        ],
                    },
                } if nori_available else {},
                "analyzer": {
                    # Korean analyzer using Nori (primary)
                    **({"korean_analyzer": {
                        "type": "custom",
                        "tokenizer": "korean_tokenizer",
                        "filter": ["lowercase", "korean_pos_filter", "nori_readingform"],
                    }} if nori_available else {}),
                    # Fallback analyzer for non-Korean or when Nori unavailable
                    "fallback_analyzer": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": ["lowercase", "asciifolding"],
                    },
                },
            },
        }
        
        # Use Korean analyzer if available, otherwise fallback
        transcript_analyzer = "korean_analyzer" if nori_available else "fallback_analyzer"
        logger.info(
            "index_analyzer_selected",
            analyzer=transcript_analyzer,
            nori_available=nori_available,
        )
        
        mappings = {
            "properties": {
                "org_id": {"type": "keyword"},
                "library_id": {"type": "keyword"},
                "library_profile_id": {"type": "keyword"},
                "library_name": {"type": "keyword"},
                "video_id": {"type": "keyword"},
                "segment_id": {"type": "keyword"},
                "start_ms": {"type": "integer"},
                "end_ms": {"type": "integer"},
                "transcript_raw": {"type": "text"},
                "transcript_norm": {
                    "type": "text",
                    "analyzer": transcript_analyzer,
                    "search_analyzer": transcript_analyzer,
                },
                # Character length for quality signals (transcript length)
                "transcript_char_count": {"type": "integer"},
                "source_type": {"type": "keyword"},
                "required_drive_nickname": {"type": "keyword"},
                "people_cluster_ids": {"type": "keyword"},
                "capture_time": {"type": "date"},
                "ingest_time": {"type": "date"},
                "thumbnail_url": {"type": "keyword", "index": False},
                "sprite_url": {"type": "keyword", "index": False},
                "word_timing_uri": {"type": "keyword", "index": False},
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
            }
        }
        
        logger.info("creating_opensearch_index", index=self.index_name, alias=self.alias_name)
        
        try:
            # Create index with alias in a single operation
            await self.client.indices.create(
                index=self.index_name,
                body={
                    "settings": settings,
                    "mappings": mappings,
                    "aliases": {
                        self.alias_name: {}  # Create alias pointing to this index
                    },
                },
            )
            logger.info(
                "opensearch_index_created",
                index=self.index_name,
                alias=self.alias_name,
                dimension=self.EMBEDDING_DIMENSION,
            )
        except Exception as e:
            if "resource_already_exists_exception" not in str(e).lower():
                raise
            logger.info("opensearch_index_already_exists", index=self.index_name)

    async def get_alias_targets(self, alias_name: str | None = None) -> list[str]:
        """
        Get list of indices that an alias currently points to.
        
        Args:
            alias_name: Alias to query. Defaults to self.alias_name.
            
        Returns:
            List of index names the alias points to. Empty list if alias doesn't exist.
        """
        alias = alias_name or self.alias_name
        try:
            alias_info = await self.client.indices.get_alias(name=alias)
            return list(alias_info.keys())
        except Exception as e:
            # Alias doesn't exist or other error
            if "alias" in str(e).lower() and "not" in str(e).lower():
                return []
            logger.warning("get_alias_targets_failed", alias=alias, error=str(e))
            return []

    async def get_index_info(self) -> dict[str, Any]:
        """
        Get current index information for diagnostics.
        
        Returns mapping details, document count, alias information,
        and mismatch detection for migration safety.
        """
        try:
            # Get alias targets
            alias_targets = await self.get_alias_targets()
            
            # Check for alias mismatch
            alias_exists = len(alias_targets) > 0
            alias_points_to_current = self.index_name in alias_targets
            alias_mismatch = alias_exists and not alias_points_to_current
            
            # Get mapping for current index (if exists)
            mapping = {}
            index_exists = await self.client.indices.exists(index=self.index_name)
            if index_exists:
                mapping = await self.client.indices.get_mapping(index=self.index_name)
            
            # Get document count (only if alias exists)
            doc_count = 0
            if alias_exists:
                try:
                    count_result = await self.client.count(index=self.alias_name)
                    doc_count = count_result.get("count", 0)
                except Exception:
                    logger.warning("opensearch_count_failed", exc_info=True)
            
            # Extract embedding dimension from mapping
            props = mapping.get(self.index_name, {}).get("mappings", {}).get("properties", {})
            embedding_config = props.get("embedding_vector", {})
            
            return {
                "alias_name": self.alias_name,
                "intended_index": self.index_name,
                "index_version": self.INDEX_VERSION,
                "index_exists": index_exists,
                "alias_exists": alias_exists,
                "alias_targets": alias_targets,
                "alias_points_to_current": alias_points_to_current,
                "alias_mismatch": alias_mismatch,
                "document_count": doc_count,
                "embedding_dimension": embedding_config.get("dimension"),
                "embedding_method": embedding_config.get("method", {}),
            }
        except Exception as e:
            logger.warning("get_index_info_failed", error=str(e))
            return {"error": str(e)}

    async def promote_alias_to_current_version(self) -> dict[str, Any]:
        """
        Atomically swap alias to point to the current versioned index.
        
        This performs a zero-downtime alias migration:
        1. Verifies target index exists
        2. Atomically removes alias from all current targets
        3. Adds alias to the current versioned index
        
        Returns:
            Dict with before/after alias targets and success status.
            
        Raises:
            ValueError: If target index doesn't exist.
        """
        # Get current alias state
        before_targets = await self.get_alias_targets()
        
        # Verify target index exists
        index_exists = await self.client.indices.exists(index=self.index_name)
        if not index_exists:
            raise ValueError(
                f"Cannot promote alias: target index '{self.index_name}' does not exist. "
                f"Run ensure_index_exists() first."
            )
        
        # Check if already pointing to current version
        if before_targets == [self.index_name]:
            logger.info(
                "alias_already_current",
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
            "promoting_alias",
            alias=self.alias_name,
            from_indices=before_targets,
            to_index=self.index_name,
        )
        
        # Atomic alias swap using update_aliases
        # This removes alias from ALL indices and adds to the new one in a single transaction
        await self.client.indices.update_aliases(
            body={
                "actions": [
                    {"remove": {"index": "*", "alias": self.alias_name}},
                    {"add": {"index": self.index_name, "alias": self.alias_name}},
                ]
            }
        )
        
        # Verify the swap
        after_targets = await self.get_alias_targets()
        
        logger.info(
            "alias_promoted",
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

    async def index_segment(self, doc_id: str, document: dict[str, Any]) -> None:
        await self.client.index(
            index=self.index_name,
            id=doc_id,
            body=document,
            params={"refresh": self.settings.opensearch_bulk_refresh},
        )

    async def bulk_index(self, documents: list[tuple[str, dict[str, Any]]]) -> None:
        if not documents:
            return
        
        actions = []
        for doc_id, doc in documents:
            actions.append({"index": {"_index": self.index_name, "_id": doc_id}})
            actions.append(doc)
        
        await self.client.bulk(body=actions, params={"refresh": self.settings.opensearch_bulk_refresh})
        logger.info("bulk_indexed_documents", count=len(documents))

    async def search_lexical(
        self,
        query: str,
        org_id: str,
        filters: dict[str, Any],
        size: int = 200,
        matched_person_cluster_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """BM25 lexical search with phrase boost for short queries."""
        filter_clauses, must_not_clauses = self._build_filter_clauses(filters)

        match_query = {
            "match": {
                "transcript_norm": {
                    "query": query,
                    "operator": "or",
                    "minimum_should_match": "50%",
                }
            }
        }

        query_word_count = len(query.split())

        person_should: dict[str, Any] | None = None
        if matched_person_cluster_ids:
            person_should = {
                "constant_score": {
                    "filter": {"terms": {"people_cluster_ids": matched_person_cluster_ids}},
                    "boost": 10.0,
                }
            }

        if query_word_count <= 3:
            should_clauses: list[dict[str, Any]] = [
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
            ]
            if person_should:
                should_clauses.append(person_should)

            search_query: dict[str, Any] = {
                "bool": {
                    "must": [{"term": {"org_id": org_id}}],
                    "should": should_clauses,
                    "minimum_should_match": 1,
                    "filter": filter_clauses,
                }
            }
        else:
            if person_should:
                search_query = {
                    "bool": {
                        "must": [{"term": {"org_id": org_id}}],
                        "should": [match_query, person_should],
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
        
        if must_not_clauses:
            search_query["bool"]["must_not"] = must_not_clauses

        body = {
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
        pos_clauses, must_not_clauses = self._build_filter_clauses(filters)
        filter_clauses = [{"term": {"org_id": org_id}}] + pos_clauses

        bool_filter: dict[str, Any] = {"must": filter_clauses}
        if must_not_clauses:
            bool_filter["must_not"] = must_not_clauses
        
        body = {
            "query": {
                "knn": {
                    "embedding_vector": {
                        "vector": embedding,
                        "k": size,
                        "filter": {"bool": bool_filter},
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
        pos_clauses, must_not_clauses = self._build_filter_clauses(filters)
        filter_clauses = [{"term": {"org_id": org_id}}] + pos_clauses

        bool_query: dict[str, Any] = {"filter": filter_clauses}
        if must_not_clauses:
            bool_query["must_not"] = must_not_clauses
        
        body = {
            "query": {"bool": bool_query},
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

    def _build_filter_clauses(
        self, filters: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        clauses: list[dict[str, Any]] = []
        must_not: list[dict[str, Any]] = []
        
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

        if filters.get("person_cluster_ids_not_in"):
            must_not.append({"terms": {"people_cluster_ids": filters["person_cluster_ids_not_in"]}})

        return clauses, must_not
