from typing import Any, cast

from opensearchpy import AsyncOpenSearch

from app.config import Settings
from app.logging_config import get_logger

logger = get_logger(__name__)


class SceneIngestMixin:
    settings: Settings = cast(Settings, cast(object, None))
    client: AsyncOpenSearch = cast(AsyncOpenSearch, cast(object, None))
    alias_name: str = ""
    index_name: str = ""

    async def index_scene(self, doc_id: str, document: dict[str, Any]) -> None:
        await self.client.index(
            index=self.index_name,
            id=doc_id,
            body=document,
            params={"refresh": self.settings.opensearch_bulk_refresh},
        )

    async def bulk_index_scenes(self, documents: list[tuple[str, dict[str, Any]]]) -> None:
        if not documents:
            return

        actions: list[dict[str, Any]] = []
        for doc_id, doc in documents:
            actions.append({"index": {"_index": self.index_name, "_id": doc_id}})
            actions.append(doc)

        await self.client.bulk(body=actions, params={"refresh": self.settings.opensearch_bulk_refresh})
        logger.info("scene_bulk_indexed_documents", count=len(documents))

    async def _resolve_doc_indices(self, doc_ids: list[str]) -> dict[str, str]:
        """Map each doc_id to the actual backing index it lives in.

        During an alias migration (e.g. heimdex_scenes → v4 AND v5), the
        alias points at multiple concrete indices. Direct mget / bulk ops
        with a hardcoded _index silently miss any doc that lives in the
        other backing index. We resolve each doc_id via an ids-query
        against the alias, which routes through all backing indices and
        returns the actual _index for each hit.

        Returns {doc_id: index_name} for docs that exist anywhere in the
        alias. Missing doc_ids (not yet indexed) are omitted from the
        returned map; callers should fall back to ``self.index_name``
        for new writes.
        """
        if not doc_ids:
            return {}

        response = await self.client.search(
            index=self.alias_name,
            body={
                "query": {"ids": {"values": doc_ids}},
                "_source": False,
                "size": len(doc_ids),
            },
        )
        return {
            hit["_id"]: hit["_index"]
            for hit in response.get("hits", {}).get("hits", [])
        }

    async def bulk_partial_update_scenes(self, updates: list[tuple[str, dict[str, Any]]]) -> None:
        if not updates:
            return

        # Resolve each doc to its actual backing index so the partial
        # update lands where the doc actually lives. Without this, a
        # bulk update with _index=self.index_name silently routes to the
        # wrong index when the alias has multiple backing indices — the
        # update either gets dropped (mget miss) or creates a duplicate
        # in the wrong index. See _resolve_doc_indices for context.
        doc_id_to_index = await self._resolve_doc_indices(
            [doc_id for doc_id, _ in updates]
        )

        actions: list[dict[str, Any]] = []
        for doc_id, partial in updates:
            target_index = doc_id_to_index.get(doc_id, self.index_name)
            actions.append({"update": {"_index": target_index, "_id": doc_id}})
            actions.append({"doc": partial})

        await self.client.bulk(body=actions, params={"refresh": self.settings.opensearch_bulk_refresh})
        logger.info("scene_bulk_partial_updated", count=len(updates))

    async def mget_scenes(self, doc_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not doc_ids:
            return {}

        # Use an ids-query via the alias rather than a direct mget. Direct
        # mget with _index=self.index_name silently misses docs that live
        # in a different backing index when the alias spans multiple
        # concrete indices (e.g. during a v4→v5 migration cutover that
        # hasn't been completed). The ids-query routes through the alias
        # and returns matching docs from any backing index. See
        # _resolve_doc_indices for the same pattern on the write path.
        response = await self.client.search(
            index=self.alias_name,
            body={
                "query": {"ids": {"values": doc_ids}},
                "_source": True,
                "size": len(doc_ids),
            },
        )

        result: dict[str, dict[str, Any]] = {}
        for hit in response.get("hits", {}).get("hits", []):
            result[hit["_id"]] = hit.get("_source") or {}
        return result

    async def get_scene_transcripts(
        self, org_id: str, video_id: str, scene_count: int
    ) -> dict[str, str]:
        """Fetch transcript_raw for all scenes of a video.

        Returns {scene_id: transcript_raw} for scenes that have transcripts.
        """
        doc_ids = [
            f"{org_id}:{video_id}_scene_{i:03d}" for i in range(scene_count)
        ]
        scenes = await self.mget_scenes(doc_ids)
        return {
            doc_id.split(":", 1)[1]: source.get("transcript_raw", "")
            for doc_id, source in scenes.items()
            if source.get("transcript_raw")
        }

    async def find_scene_ids_by_video_id(self, org_id: str, video_id: str) -> list[str]:
        body: dict[str, Any] = {
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"org_id": org_id}},
                        {"term": {"video_id": video_id}},
                    ]
                }
            },
            "_source": False,
            "size": 1000,
        }
        response = await self.client.search(index=self.index_name, body=body)
        return [hit["_id"] for hit in response.get("hits", {}).get("hits", [])]

    async def delete_scenes_by_video_id(self, org_id: str, video_id: str) -> int:
        body = {
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"org_id": org_id}},
                        {"term": {"video_id": video_id}},
                    ]
                }
            }
        }
        response = await self.client.delete_by_query(
            index=self.alias_name,
            body=body,
            params={"refresh": "true"},
        )
        return int(response.get("deleted", 0))
