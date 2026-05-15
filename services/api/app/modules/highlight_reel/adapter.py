"""OpenSearch + DB adapter implementing SceneDataPort.

This is the only file in the highlight_reel module that touches
infrastructure (OpenSearch queries, DB repositories). All other
files depend on the port protocol, not this adapter.
"""
from __future__ import annotations

from uuid import UUID

from app.modules.highlight_reel.domain import SceneRecord
from app.modules.people.repository import PeopleVideoExclusionRepository
from app.modules.search.scene_client import SceneSearchClient


class OpenSearchSceneDataAdapter:
    """Fetches scene data from OpenSearch and exclusion data from Postgres."""

    def __init__(
        self,
        scene_client: SceneSearchClient,
        video_excl_repo: PeopleVideoExclusionRepository,
    ) -> None:
        self._scene_client = scene_client
        self._video_excl_repo = video_excl_repo

    async def get_person_scenes(
        self,
        org_id: str,
        person_cluster_id: str,
        limit: int = 1000,
    ) -> list[SceneRecord]:
        body = {
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"org_id": org_id}},
                        {"term": {"content_type": "video"}},
                        {"term": {"people_cluster_ids": person_cluster_id}},
                    ],
                }
            },
            "_source": ["scene_id", "video_id", "start_ms", "end_ms"],
            "sort": [{"video_id": "asc"}, {"start_ms": "asc"}],
            "size": limit,
        }

        response = await self._scene_client.client.search(
            index=self._scene_client.alias_name,
            body=body,
        )

        return [
            SceneRecord(
                scene_id=hit["_source"]["scene_id"],
                video_id=hit["_source"]["video_id"],
                start_ms=hit["_source"]["start_ms"],
                end_ms=hit["_source"]["end_ms"],
            )
            for hit in response["hits"]["hits"]
        ]

    async def get_excluded_video_ids(
        self,
        org_id: UUID,
        user_id: UUID,
        person_cluster_id: str,
    ) -> list[str]:
        return await self._video_excl_repo.list_by_user_and_person(
            org_id, user_id, person_cluster_id,
        )

    async def get_video_titles(
        self,
        org_id: str,
        person_cluster_id: str,
    ) -> dict[str, str | None]:
        videos = await self._scene_client.get_videos_by_person(
            org_id, person_cluster_id,
        )
        return {v["video_id"]: v["video_title"] for v in videos}
