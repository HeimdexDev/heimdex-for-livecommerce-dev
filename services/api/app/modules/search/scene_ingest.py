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

    async def bulk_partial_update_scenes(self, updates: list[tuple[str, dict[str, Any]]]) -> None:
        if not updates:
            return

        actions: list[dict[str, Any]] = []
        for doc_id, partial in updates:
            actions.append({"update": {"_index": self.index_name, "_id": doc_id}})
            actions.append({"doc": partial})

        await self.client.bulk(body=actions, params={"refresh": self.settings.opensearch_bulk_refresh})
        logger.info("scene_bulk_partial_updated", count=len(updates))

    async def mget_scenes(self, doc_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not doc_ids:
            return {}

        body = {"docs": [{"_index": self.index_name, "_id": did} for did in doc_ids]}
        response = await self.client.mget(body=body)

        result: dict[str, dict[str, Any]] = {}
        for doc in response.get("docs", []):
            if doc.get("found"):
                result[doc["_id"]] = doc["_source"]
        return result

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
