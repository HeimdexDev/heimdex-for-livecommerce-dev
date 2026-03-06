from typing import Any, cast

from opensearchpy import AsyncOpenSearch
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import Settings, get_settings
from app.logging_config import get_logger
from app.modules.search.client import get_opensearch_client

logger = get_logger(__name__)


class SceneIndexMixin:
    settings: Settings = cast(Settings, cast(object, None))
    client: AsyncOpenSearch = cast(AsyncOpenSearch, cast(object, None))
    alias_name: str = ""
    index_name: str = ""
    EMBEDDING_DIMENSION: int = 0
    VISUAL_EMBEDDING_DIMENSION: int = 0
    INDEX_VERSION: str = ""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = get_opensearch_client()
        self.alias_name = f"{self.settings.opensearch_index_prefix}_scenes"
        self.index_name = f"{self.alias_name}_{self.INDEX_VERSION}"

    async def close(self) -> None:
        await self.client.close()

    async def _check_nori_available(self) -> bool:
        """Check if the Nori analyzer plugin is installed."""
        try:
            response = await self.client.cat.plugins(params={"format": "json"})
            plugins = [p.get("component", "") for p in response]
            nori_installed = any("analysis-nori" in p for p in plugins)
            logger.info("scene_nori_plugin_check", installed=nori_installed)
            return nori_installed
        except Exception as e:
            logger.warning("scene_nori_plugin_check_failed", error=str(e))
            return False

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
                "knn.algo_param.ef_search": 256,
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
                "org_id": {"type": "keyword"},
                "library_id": {"type": "keyword"},
                "video_id": {"type": "keyword"},
                "video_title": {
                    "type": "keyword",
                    "fields": {
                        "nori": {
                            "type": "text",
                            "analyzer": transcript_analyzer,
                            "search_analyzer": transcript_analyzer,
                        }
                    },
                },
                "scene_id": {"type": "keyword"},
                "start_ms": {"type": "integer"},
                "end_ms": {"type": "integer"},
                "transcript_raw": {"type": "text"},
                "transcript_norm": {
                    "type": "text",
                    "analyzer": transcript_analyzer,
                    "search_analyzer": transcript_analyzer,
                },
                "transcript_char_count": {"type": "integer"},
                "ocr_text_raw": {"type": "text"},
                "ocr_text_norm": {
                    "type": "text",
                    "analyzer": transcript_analyzer,
                    "search_analyzer": transcript_analyzer,
                },
                "ocr_char_count": {"type": "integer"},
                "scene_caption": {
                    "type": "text",
                    "analyzer": transcript_analyzer,
                    "search_analyzer": transcript_analyzer,
                },
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
                "visual_embedding": {
                    "type": "knn_vector",
                    "dimension": self.VISUAL_EMBEDDING_DIMENSION,
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "lucene",
                        "parameters": {"ef_construction": 128, "m": 16},
                    },
                },
                "people_cluster_ids": {"type": "keyword"},
                "keyword_tags": {"type": "keyword"},
                "product_tags": {"type": "keyword"},
                "product_entities": {"type": "keyword"},
                "speaker_transcript": {
                    "type": "text",
                    "analyzer": transcript_analyzer,
                    "search_analyzer": transcript_analyzer,
                },
                "speaker_count": {"type": "integer"},
                "speech_segment_count": {"type": "integer"},
                "keyframe_timestamp_ms": {"type": "integer"},
                "thumbnail_url": {"type": "keyword", "index": False},
                "source_type": {"type": "keyword"},
                "web_view_link": {"type": "keyword", "index": False},
                "required_drive_nickname": {"type": "keyword"},
                "source_path": {"type": "keyword"},
                "capture_time": {"type": "date"},
                "ingest_time": {"type": "date"},
                "embedding_version": {"type": "keyword"},
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
