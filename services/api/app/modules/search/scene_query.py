from typing import Any, cast

from opensearchpy import AsyncOpenSearch

from app.config import Settings, get_settings


class SceneQueryMixin:
    settings: Settings = cast(Settings, cast(object, None))
    client: AsyncOpenSearch = cast(AsyncOpenSearch, cast(object, None))
    alias_name: str = ""
    index_name: str = ""

    async def search_metadata(
        self,
        query: str,
        org_id: str,
        filters: dict[str, Any],
        size: int = 200,
    ) -> list[dict[str, Any]]:
        filter_clauses, must_not_clauses = self._build_filter_clauses(filters)

        query_word_count = len(query.split())
        includes_images = "image" in (filters.get("content_types") or ["video"])
        escaped = query.replace("\\", "\\\\").replace("*", "\\*").replace("?", "\\?")

        if query_word_count <= 3:
            should_clauses: list[dict[str, Any]] = [
                {
                    "match": {
                        "video_title.nori": {
                            "query": query,
                            "operator": "or",
                            "minimum_should_match": "50%",
                            "boost": 2.0,
                        }
                    }
                },
                {
                    "match_phrase": {
                        "video_title.nori": {
                            "query": query,
                            "boost": 4.0,
                            "slop": 1,
                        }
                    }
                },
                {
                    "wildcard": {
                        "video_title": {
                            "value": f"*{escaped}*",
                            "case_insensitive": True,
                            "boost": 2.0,
                        }
                    }
                },
                {
                    "match": {
                        "source_path": {
                            "query": query,
                            "operator": "or",
                            "minimum_should_match": "50%",
                            "boost": 0.5,
                        }
                    }
                },
            ]
            if includes_images:
                should_clauses.extend([
                    {
                        "match": {
                            "filename_text": {
                                "query": query,
                                "operator": "or",
                                "minimum_should_match": "50%",
                                "boost": 2.0,
                            }
                        }
                    },
                    {
                        "match_phrase": {
                            "filename_text": {
                                "query": query,
                                "boost": 4.0,
                                "slop": 1,
                            }
                        }
                    },
                ])
            search_query: dict[str, Any] = {
                "bool": {
                    "must": [{"term": {"org_id": org_id}}],
                    "should": should_clauses,
                    "minimum_should_match": 1,
                    "filter": filter_clauses,
                }
            }
        else:
            long_should: list[dict[str, Any]] = [
                {
                    "match": {
                        "video_title.nori": {
                            "query": query,
                            "operator": "or",
                            "minimum_should_match": "50%",
                            "boost": 2.0,
                        }
                    }
                },
                {
                    "wildcard": {
                        "video_title": {
                            "value": f"*{escaped}*",
                            "case_insensitive": True,
                            "boost": 2.0,
                        }
                    }
                },
                {
                    "match": {
                        "source_path": {
                            "query": query,
                            "operator": "or",
                            "minimum_should_match": "50%",
                            "boost": 0.5,
                        }
                    }
                },
            ]
            if includes_images:
                long_should.append({
                    "match": {
                        "filename_text": {
                            "query": query,
                            "operator": "or",
                            "minimum_should_match": "50%",
                            "boost": 2.0,
                        }
                    }
                })
            search_query = {
                "bool": {
                    "must": [{"term": {"org_id": org_id}}],
                    "should": long_should,
                    "minimum_should_match": 1,
                    "filter": filter_clauses,
                }
            }

        if must_not_clauses:
            search_query["bool"]["must_not"] = must_not_clauses

        body: dict[str, Any] = {
            "query": search_query,
            "size": size,
            "_source": True,
        }

        response = await self.client.search(index=self.alias_name, body=body)
        return response["hits"]["hits"]

    async def search_lexical(
        self,
        query: str,
        org_id: str,
        filters: dict[str, Any],
        size: int = 200,
        include_ocr: bool | None = None,
        matched_person_cluster_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        settings = get_settings()
        raw_ocr_enabled = getattr(settings, "ocr_search_enabled", True)
        default_ocr_enabled = raw_ocr_enabled if isinstance(raw_ocr_enabled, bool) else False
        raw_ocr_bm25_boost = getattr(settings, "ocr_bm25_boost", 0.6)
        ocr_bm25_boost = float(raw_ocr_bm25_boost) if isinstance(raw_ocr_bm25_boost, int | float) else 0.6
        filter_clauses, must_not_clauses = self._build_filter_clauses(filters)
        ocr_enabled = include_ocr if include_ocr is not None else default_ocr_enabled
        includes_images = "image" in (filters.get("content_types") or ["video"])

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

        title_bm25_boost = 1.5

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
                {
                    "match": {
                        "video_title.nori": {
                            "query": query,
                            "operator": "or",
                            "minimum_should_match": "50%",
                            "boost": title_bm25_boost,
                        }
                    }
                },
                {
                    "match_phrase": {
                        "video_title.nori": {
                            "query": query,
                            "boost": title_bm25_boost * 2,
                            "slop": 1,
                        }
                    }
                },
            ]
            if ocr_enabled:
                should_clauses.extend(
                    [
                        {
                            "match": {
                                "ocr_text_norm": {
                                    "query": query,
                                    "operator": "or",
                                    "minimum_should_match": "50%",
                                    "boost": ocr_bm25_boost,
                                }
                            }
                        },
                        {
                            "match_phrase": {
                                "ocr_text_norm": {
                                    "query": query,
                                    "boost": ocr_bm25_boost * 2,
                                    "slop": 1,
                                }
                            }
                        },
                    ]
                )

            should_clauses.extend(
                [
                    {
                        "match": {
                            "scene_caption": {
                                "query": query,
                                "operator": "or",
                                "minimum_should_match": "50%",
                                "boost": 1.0,
                            }
                        }
                    },
                    {
                        "match_phrase": {
                            "scene_caption": {
                                "query": query,
                                "boost": 2.0,
                                "slop": 1,
                            }
                        }
                    },
                ]
            )

            should_clauses.extend(
                [
                    {
                        "match": {
                            "speaker_transcript": {
                                "query": query,
                                "operator": "or",
                                "minimum_should_match": "50%",
                                "boost": 0.9,
                            }
                        }
                    },
                    {
                        "match_phrase": {
                            "speaker_transcript": {
                                "query": query,
                                "boost": 1.8,
                                "slop": 1,
                            }
                        }
                    },
                ]
            )

            if includes_images:
                should_clauses.extend([
                    {
                        "match": {
                            "filename_text": {
                                "query": query,
                                "operator": "or",
                                "minimum_should_match": "50%",
                                "boost": 2.0,
                            }
                        }
                    },
                    {
                        "match_phrase": {
                            "filename_text": {
                                "query": query,
                                "boost": 4.0,
                                "slop": 1,
                            }
                        }
                    },
                ])

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
            optional_should: list[dict[str, Any]] = [
                {
                    "match": {
                        "video_title.nori": {
                            "query": query,
                            "operator": "or",
                            "minimum_should_match": "50%",
                            "boost": title_bm25_boost,
                        }
                    }
                },
            ]
            if ocr_enabled:
                optional_should.append(
                    {
                        "match": {
                            "ocr_text_norm": {
                                "query": query,
                                "operator": "or",
                                "minimum_should_match": "50%",
                                "boost": ocr_bm25_boost,
                            }
                        }
                    }
                )

            optional_should.append(
                {
                    "match": {
                        "scene_caption": {
                            "query": query,
                            "operator": "or",
                            "minimum_should_match": "50%",
                            "boost": 1.0,
                        }
                    }
                }
            )

            optional_should.append(
                {
                    "match": {
                        "speaker_transcript": {
                            "query": query,
                            "operator": "or",
                            "minimum_should_match": "50%",
                            "boost": 0.9,
                        }
                    }
                }
            )

            if includes_images:
                optional_should.append({
                    "match": {
                        "filename_text": {
                            "query": query,
                            "operator": "or",
                            "minimum_should_match": "50%",
                            "boost": 2.0,
                        }
                    }
                })

            if person_should:
                all_should = [match_query, person_should] + optional_should
                search_query = {
                    "bool": {
                        "must": [{"term": {"org_id": org_id}}],
                        "should": all_should,
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
                        "should": optional_should,
                        "filter": filter_clauses,
                    }
                }

        if must_not_clauses:
            search_query["bool"]["must_not"] = must_not_clauses

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
        pos_clauses, must_not_clauses = self._build_filter_clauses(filters)
        filter_clauses = [{"term": {"org_id": org_id}}] + pos_clauses

        knn_filter: dict[str, Any] = {"bool": {"must": filter_clauses}}
        if must_not_clauses:
            knn_filter["bool"]["must_not"] = must_not_clauses

        body: dict[str, Any] = {
            "query": {
                "knn": {
                    "embedding_vector": {
                        "vector": embedding,
                        "k": size,
                        "filter": knn_filter,
                    }
                }
            },
            "size": size,
            "_source": True,
        }

        response = await self.client.search(index=self.alias_name, body=body)
        return response["hits"]["hits"]

    async def search_visual_vector(
        self,
        visual_embedding: list[float],
        org_id: str,
        filters: dict[str, Any],
        size: int = 200,
    ) -> list[dict[str, Any]]:
        pos_clauses, must_not_clauses = self._build_filter_clauses(filters)
        filter_clauses = [{"term": {"org_id": org_id}}] + pos_clauses

        knn_filter: dict[str, Any] = {"bool": {"must": filter_clauses}}
        if must_not_clauses:
            knn_filter["bool"]["must_not"] = must_not_clauses

        body: dict[str, Any] = {
            "query": {
                "knn": {
                    "visual_embedding": {
                        "vector": visual_embedding,
                        "k": size,
                        "filter": knn_filter,
                    }
                }
            },
            "size": size,
            "_source": True,
        }

        response = await self.client.search(index=self.alias_name, body=body)
        return response["hits"]["hits"]

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

        if filters.get("person_video_exclusions"):
            for person_cluster_id, video_id in filters["person_video_exclusions"]:
                must_not.append({
                    "bool": {
                        "must": [
                            {"term": {"video_id": video_id}},
                            {"term": {"people_cluster_ids": person_cluster_id}},
                        ]
                    }
                })

        _TAG_IN_FIELDS = {
            "keyword_tags_in": "keyword_tags",
            "product_tags_in": "product_tags",
            "product_entities_in": "product_entities",
        }
        for filter_key, os_field in _TAG_IN_FIELDS.items():
            vals = filters.get(filter_key)
            if vals:
                clauses.append({"terms": {os_field: vals}})

        _TAG_NOT_IN_FIELDS = {
            "keyword_tags_not_in": "keyword_tags",
            "product_tags_not_in": "product_tags",
            "product_entities_not_in": "product_entities",
        }
        for filter_key, os_field in _TAG_NOT_IN_FIELDS.items():
            vals = filters.get(filter_key)
            if vals:
                must_not.append({"terms": {os_field: vals}})

        content_types = filters.get("content_types")
        if content_types:
            clauses.append({"terms": {"content_type": content_types}})

        return clauses, must_not
