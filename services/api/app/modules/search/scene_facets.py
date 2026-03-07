from typing import TYPE_CHECKING, Any, cast

from opensearchpy import AsyncOpenSearch

from app.config import Settings
from app.logging_config import get_logger

logger = get_logger(__name__)


class SceneFacetsMixin:
    settings: Settings = cast(Settings, cast(object, None))
    client: AsyncOpenSearch = cast(AsyncOpenSearch, cast(object, None))
    alias_name: str = ""
    index_name: str = ""

    if TYPE_CHECKING:
        def _build_filter_clauses(
            self, filters: dict[str, Any],
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]: ...

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

        body: dict[str, Any] = {
            "query": {"bool": bool_query},
            "size": 0,
            "aggs": {
                "libraries": {"terms": {"field": "library_id", "size": self.settings.opensearch_facet_size}},
                "source_types": {"terms": {"field": "source_type", "size": 10}},
                "people": {"terms": {"field": "people_cluster_ids", "size": self.settings.opensearch_facet_size}},
            },
        }

        response = await self.client.search(index=self.alias_name, body=body)

        return {
            "libraries": response["aggregations"]["libraries"]["buckets"],
            "source_types": response["aggregations"]["source_types"]["buckets"],
            "people": response["aggregations"]["people"]["buckets"],
        }

    async def aggregate_videos(
        self,
        org_id: str,
        *,
        library_id: str | None = None,
        source_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        sort: str = "latest",
        page_size: int = 20,
        after_key: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        filter_clauses: list[dict[str, Any]] = [{"term": {"org_id": org_id}}]
        if library_id:
            filter_clauses.append({"term": {"library_id": library_id}})
        if source_type:
            filter_clauses.append({"term": {"source_type": source_type}})
        if date_from or date_to:
            date_range: dict[str, str] = {}
            if date_from:
                date_range["gte"] = date_from
            if date_to:
                date_range["lte"] = date_to
            filter_clauses.append({"bool": {"should": [
                {"range": {"capture_time": date_range}},
                {"bool": {"must_not": {"exists": {"field": "capture_time"}}, "filter": {"range": {"ingest_time": date_range}}}},
            ], "minimum_should_match": 1}})

        composite_sources: list[dict[str, Any]] = [
            {"video_id": {"terms": {"field": "video_id", "order": "desc"}}},
        ]

        aggs: dict[str, Any] = {
            "videos": {
                "composite": {
                    "sources": composite_sources,
                    "size": page_size,
                },
                "aggs": {
                    "scene_count": {"value_count": {"field": "scene_id"}},
                    "min_start_ms": {"min": {"field": "start_ms"}},
                    "max_end_ms": {"max": {"field": "end_ms"}},
                    "earliest_ingest": {"min": {"field": "ingest_time"}},
                    "latest_ingest": {"max": {"field": "ingest_time"}},
                    "min_keyframe_ms": {"min": {"field": "keyframe_timestamp_ms"}},
                    "library_id": {"terms": {"field": "library_id", "size": 1}},
                    "video_title": {"terms": {"field": "video_title", "size": 1}},
                    "source_type": {"terms": {"field": "source_type", "size": 1}},
                    "required_drive_nickname": {"terms": {"field": "required_drive_nickname", "size": 1}},
                    "web_view_link": {"terms": {"field": "web_view_link", "size": 1}},
                    "source_path": {"terms": {"field": "source_path", "size": 1}},
                    "keyword_tags": {"terms": {"field": "keyword_tags", "size": 10}},
                    "product_tags": {"terms": {"field": "product_tags", "size": 10}},
                    "people_count": {"cardinality": {"field": "people_cluster_ids"}},
                    "earliest_capture": {"min": {"field": "capture_time"}},
                },
            },
            "total_videos": {"cardinality": {"field": "video_id", "precision_threshold": 10000}},
            "facet_libraries": {"terms": {"field": "library_id", "size": 100}},
            "facet_source_types": {"terms": {"field": "source_type", "size": 10}},
        }

        if after_key:
            aggs["videos"]["composite"]["after"] = after_key

        body: dict[str, Any] = {
            "query": {"bool": {"filter": filter_clauses}},
            "size": 0,
            "aggs": aggs,
        }

        response = await self.client.search(index=self.alias_name, body=body)
        agg_result = response["aggregations"]

        videos = []
        for bucket in agg_result["videos"]["buckets"]:
            video_id = bucket["key"]["video_id"]
            lib_buckets = bucket["library_id"]["buckets"]
            title_buckets = bucket["video_title"]["buckets"]
            src_buckets = bucket["source_type"]["buckets"]
            drive_buckets = bucket["required_drive_nickname"]["buckets"]
            web_view_link_buckets = bucket.get("web_view_link", {}).get("buckets", [])
            sp_buckets = bucket.get("source_path", {}).get("buckets", [])
            kw_buckets = bucket["keyword_tags"]["buckets"]
            pt_buckets = bucket["product_tags"]["buckets"]
            keyframe_agg = bucket.get("min_keyframe_ms", {})
            keyframe_ms = int(keyframe_agg.get("value") or 0)

            videos.append({
                "video_id": video_id,
                "video_title": title_buckets[0]["key"] if title_buckets else None,
                "library_id": lib_buckets[0]["key"] if lib_buckets else None,
                "source_type": src_buckets[0]["key"] if src_buckets else None,
                "scene_count": int(bucket["scene_count"]["value"]),
                "first_scene_start_ms": int(bucket["min_start_ms"]["value"] or 0),
                "last_scene_end_ms": int(bucket["max_end_ms"]["value"] or 0),
                "earliest_ingest_time": bucket["earliest_ingest"]["value_as_string"] if bucket["earliest_ingest"]["value"] else None,
                "latest_ingest_time": bucket["latest_ingest"]["value_as_string"] if bucket["latest_ingest"]["value"] else None,
                "first_scene_keyframe_ms": keyframe_ms,
                "keyword_tags": [b["key"] for b in kw_buckets],
                "product_tags": [b["key"] for b in pt_buckets],
                "people_count": int(bucket["people_count"]["value"]),
                "required_drive_nickname": drive_buckets[0]["key"] if drive_buckets else None,
                "web_view_link": web_view_link_buckets[0]["key"] if web_view_link_buckets else None,
                "source_path": sp_buckets[0]["key"] if sp_buckets else None,
                "capture_time": bucket.get("earliest_capture", {}).get("value_as_string") if bucket.get("earliest_capture", {}).get("value") else None,
            })

        if sort == "latest":
            videos.sort(key=lambda v: v["capture_time"] or v["latest_ingest_time"] or "", reverse=True)
        elif sort == "oldest":
            videos.sort(key=lambda v: v["capture_time"] or v["latest_ingest_time"] or "")
        elif sort == "alpha_asc":
            videos.sort(key=lambda v: (v["video_title"] or "").lower())
        elif sort == "alpha_desc":
            videos.sort(key=lambda v: (v["video_title"] or "").lower(), reverse=True)
        else:
            videos.sort(key=lambda v: v["capture_time"] or v["latest_ingest_time"] or "", reverse=True)

        after_key_result = agg_result["videos"].get("after_key")

        return {
            "videos": videos,
            "total": int(agg_result["total_videos"]["value"]),
            "next_cursor": after_key_result,
            "facets": {
                "libraries": agg_result["facet_libraries"]["buckets"],
                "source_types": agg_result["facet_source_types"]["buckets"],
            },
        }

    async def get_video_scenes(
        self,
        org_id: str,
        video_id: str,
        *,
        page_size: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"org_id": org_id}},
                        {"term": {"video_id": video_id}},
                    ],
                }
            },
            "sort": [{"start_ms": "asc"}],
            "from": offset,
            "size": page_size,
            "_source": [
                "scene_id", "start_ms", "end_ms", "transcript_raw",
                "transcript_char_count", "scene_caption", "keyword_tags", "product_tags",
                "product_entities", "speech_segment_count",
                "people_cluster_ids", "ingest_time", "keyframe_timestamp_ms",
                "speaker_transcript", "speaker_count",
                "video_title", "source_type", "source_path", "capture_time",
                "web_view_link",
                "library_id",
            ],
        }

        response = await self.client.search(index=self.alias_name, body=body)

        scenes = []
        for hit in response["hits"]["hits"]:
            src = hit["_source"]
            scenes.append({
                "scene_id": src.get("scene_id", hit["_id"]),
                "start_ms": src.get("start_ms", 0),
                "end_ms": src.get("end_ms", 0),
                "transcript_raw": src.get("transcript_raw", ""),
                "transcript_char_count": src.get("transcript_char_count", 0),
                "scene_caption": src.get("scene_caption", ""),
                "keyword_tags": src.get("keyword_tags", []),
                "product_tags": src.get("product_tags", []),
                "product_entities": src.get("product_entities", []),
                "speech_segment_count": src.get("speech_segment_count", 0),
                "people_cluster_ids": src.get("people_cluster_ids", []),
                "ingest_time": src.get("ingest_time"),
                "keyframe_timestamp_ms": src.get("keyframe_timestamp_ms", 0),
                "speaker_transcript": src.get("speaker_transcript", ""),
                "speaker_count": src.get("speaker_count", 0),
                "web_view_link": src.get("web_view_link"),
            })

        total = response["hits"]["total"]
        total_count = total["value"] if isinstance(total, dict) else total

        video_meta: dict[str, Any] = {}
        if response["hits"]["hits"]:
            first_src = response["hits"]["hits"][0]["_source"]
            video_meta = {
                "video_title": first_src.get("video_title"),
                "source_type": first_src.get("source_type"),
                "source_path": first_src.get("source_path"),
                "web_view_link": first_src.get("web_view_link"),
                "capture_time": first_src.get("capture_time"),
                "library_id": first_src.get("library_id"),
                "earliest_ingest_time": first_src.get("ingest_time"),
            }

        return {
            "scenes": scenes,
            "total": int(total_count),
            **video_meta,
        }

    async def get_videos_by_person(
        self,
        org_id: str,
        person_cluster_id: str,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"org_id": org_id}},
                        {"term": {"people_cluster_ids": person_cluster_id}},
                    ],
                }
            },
            "size": 0,
            "aggs": {
                "by_video": {
                    "terms": {"field": "video_id", "size": 200},
                    "aggs": {
                        "video_title": {"terms": {"field": "video_title", "size": 1}},
                        "scene_count": {"value_count": {"field": "scene_id"}},
                    },
                },
            },
        }

        response = await self.client.search(index=self.alias_name, body=body)
        buckets = response["aggregations"]["by_video"]["buckets"]

        return [
            {
                "video_id": bucket["key"],
                "video_title": (
                    bucket["video_title"]["buckets"][0]["key"]
                    if bucket["video_title"]["buckets"]
                    else None
                ),
                "scene_count": int(bucket["scene_count"]["value"]),
            }
            for bucket in buckets
        ]

    async def get_person_timeline(
        self,
        org_id: str,
        person_cluster_id: str,
    ) -> list[dict[str, Any]]:
        video_id_body: dict[str, Any] = {
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"org_id": org_id}},
                        {"term": {"people_cluster_ids": person_cluster_id}},
                    ],
                }
            },
            "size": 0,
            "aggs": {
                "video_ids": {
                    "terms": {"field": "video_id", "size": 200},
                },
            },
        }

        resp1 = await self.client.search(
            index=self.alias_name, body=video_id_body,
        )
        video_ids = [
            b["key"]
            for b in resp1["aggregations"]["video_ids"]["buckets"]
        ]
        if not video_ids:
            return []

        all_scenes_body: dict[str, Any] = {
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"org_id": org_id}},
                        {"terms": {"video_id": video_ids}},
                    ],
                }
            },
            "size": 10000,
            "sort": [
                {"video_id": "asc"},
                {"start_ms": "asc"},
            ],
            "_source": [
                "scene_id",
                "video_id",
                "video_title",
                "start_ms",
                "end_ms",
                "people_cluster_ids",
            ],
        }

        resp2 = await self.client.search(
            index=self.alias_name, body=all_scenes_body,
        )

        videos_map: dict[str, dict[str, Any]] = {}
        for hit in resp2["hits"]["hits"]:
            src = hit["_source"]
            vid = src["video_id"]
            cluster_ids = src.get("people_cluster_ids") or []

            if vid not in videos_map:
                videos_map[vid] = {
                    "video_id": vid,
                    "video_title": src.get("video_title"),
                    "scenes": [],
                }

            videos_map[vid]["scenes"].append({
                "scene_id": src["scene_id"],
                "start_ms": src.get("start_ms", 0),
                "end_ms": src.get("end_ms", 0),
                "has_person": person_cluster_id in cluster_ids,
            })

        return [
            {**v, "total_scenes": len(v["scenes"])}
            for v in videos_map.values()
        ]

    async def get_representative_scenes_for_people(
        self,
        org_id: str,
        person_cluster_ids: list[str],
    ) -> dict[str, dict[str, str]]:
        if not person_cluster_ids:
            return {}

        body_parts: list[dict[str, Any]] = []
        for cluster_id in person_cluster_ids:
            body_parts.append({"index": self.alias_name})
            body_parts.append({
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"org_id": org_id}},
                            {"term": {"people_cluster_ids": cluster_id}},
                        ],
                    }
                },
                "sort": [{"ingest_time": "desc"}],
                "size": 1,
                "_source": ["video_id", "scene_id"],
            })

        response = await self.client.msearch(body=body_parts)

        result: dict[str, dict[str, str]] = {}
        for i, resp in enumerate(response["responses"]):
            hits = resp.get("hits", {}).get("hits", [])
            if hits:
                src = hits[0]["_source"]
                result[person_cluster_ids[i]] = {
                    "video_id": src["video_id"],
                    "scene_id": src["scene_id"],
                }

        return result

    async def remove_person_cluster_id(
        self,
        org_id: str,
        person_cluster_id: str,
    ) -> int:
        body: dict[str, Any] = {
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"org_id": org_id}},
                        {"term": {"people_cluster_ids": person_cluster_id}},
                    ],
                }
            },
            "script": {
                "source": (
                    "if (ctx._source.people_cluster_ids != null) {"
                    "  ctx._source.people_cluster_ids.removeIf("
                    "    id -> id.equals(params.cluster_id)"
                    "  );"
                    "}"
                ),
                "lang": "painless",
                "params": {"cluster_id": person_cluster_id},
            },
        }

        response = await self.client.update_by_query(
            index=self.alias_name,
            body=body,
            params={"refresh": "true"},
        )
        updated = int(response.get("updated", 0))
        logger.info(
            "remove_person_cluster_id_complete",
            org_id=org_id,
            person_cluster_id=person_cluster_id,
            scenes_updated=updated,
        )
        return updated

    async def replace_person_cluster_id(
        self,
        org_id: str,
        source_cluster_id: str,
        target_cluster_id: str,
    ) -> int:
        body: dict[str, Any] = {
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"org_id": org_id}},
                        {"term": {"people_cluster_ids": source_cluster_id}},
                    ],
                }
            },
            "script": {
                "source": (
                    "if (ctx._source.people_cluster_ids != null) {"
                    "  ctx._source.people_cluster_ids.removeIf("
                    "    id -> id.equals(params.source_id)"
                    "  );"
                    "  if (!ctx._source.people_cluster_ids.contains(params.target_id)) {"
                    "    ctx._source.people_cluster_ids.add(params.target_id);"
                    "  }"
                    "}"
                ),
                "lang": "painless",
                "params": {
                    "source_id": source_cluster_id,
                    "target_id": target_cluster_id,
                },
            },
        }

        response = await self.client.update_by_query(
            index=self.alias_name,
            body=body,
            params={"refresh": "true"},
        )
        updated = int(response.get("updated", 0))
        logger.info(
            "replace_person_cluster_id_complete",
            org_id=org_id,
            source_cluster_id=source_cluster_id,
            target_cluster_id=target_cluster_id,
            scenes_updated=updated,
        )
        return updated

    async def get_video_stats(
        self,
        org_id: str,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "query": {
                "bool": {
                    "filter": [{"term": {"org_id": org_id}}],
                }
            },
            "size": 0,
            "aggs": {
                "total_videos": {"cardinality": {"field": "video_id", "precision_threshold": 10000}},
                "total_libraries": {"cardinality": {"field": "library_id", "precision_threshold": 1000}},
                "source_breakdown": {"terms": {"field": "source_type", "size": 10}},
                "latest_ingest": {"max": {"field": "ingest_time"}},
                "latest_capture": {"max": {"field": "capture_time"}},
                "scenes_last_24h": {
                    "filter": {"range": {"ingest_time": {"gte": "now-24h"}}},
                },
                "scenes_last_7d": {
                    "filter": {"range": {"ingest_time": {"gte": "now-7d"}}},
                },
            },
        }

        response = await self.client.search(index=self.alias_name, body=body)
        aggs = response["aggregations"]

        total_scenes = response["hits"]["total"]
        total_scenes_count = total_scenes["value"] if isinstance(total_scenes, dict) else total_scenes

        source_breakdown = {
            bucket["key"]: bucket["doc_count"]
            for bucket in aggs["source_breakdown"]["buckets"]
        }

        return {
            "total_videos": int(aggs["total_videos"]["value"]),
            "total_scenes": int(total_scenes_count),
            "total_libraries": int(aggs["total_libraries"]["value"]),
            "source_breakdown": source_breakdown,
            "latest_ingest_time": aggs["latest_ingest"]["value_as_string"] if aggs["latest_ingest"]["value"] else None,
            "latest_capture_time": aggs.get("latest_capture", {}).get("value_as_string") if aggs.get("latest_capture", {}).get("value") else None,
            "scenes_last_24h": int(aggs["scenes_last_24h"]["doc_count"]),
            "scenes_last_7d": int(aggs["scenes_last_7d"]["doc_count"]),
        }
