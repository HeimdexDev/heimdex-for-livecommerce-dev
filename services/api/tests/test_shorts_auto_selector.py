"""Selector tests: OS query construction per mode + result parsing."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.shorts_auto.selector import AutoShortsSelector
from heimdex_media_contracts.shorts.scorer import ScoringMode


def _mock_scene_client(hits: list[dict] | None = None):
    """Build a fake scene OS client with a recordable .client.search()."""
    inner = AsyncMock()
    inner.search = AsyncMock(
        return_value={"hits": {"hits": hits or []}}
    )
    client = SimpleNamespace(client=inner, alias_name="heimdex_scenes")
    return client


def _scene_hit(scene_id: str, *, index: int, start_ms: int, end_ms: int, **extra):
    src = {
        "scene_id": scene_id,
        "video_id": "vid",
        "index": index,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "keyframe_timestamp_ms": (start_ms + end_ms) // 2,
        "people_cluster_ids": [],
        "keyword_tags": [],
        "product_tags": [],
        "product_entities": [],
    }
    src.update(extra)
    return {"_id": f"org:{scene_id}", "_source": src}


@pytest.mark.asyncio
class TestQueryConstruction:
    async def test_both_mode_no_extra_filters(self):
        client = _mock_scene_client()
        selector = AutoShortsSelector(client)
        await selector.fetch_candidates(uuid4(), "vid", ScoringMode.BOTH)
        body = client.client.search.call_args.kwargs["body"]
        filters = body["query"]["bool"]["filter"]
        # Only org_id + video_id filters; no mode-specific must_not
        assert any(f.get("term", {}).get("video_id") == "vid" for f in filters)
        assert body["query"]["bool"]["must_not"] == []

    async def test_human_mode_filters_people_cluster_id(self):
        client = _mock_scene_client()
        selector = AutoShortsSelector(client)
        await selector.fetch_candidates(
            uuid4(), "vid", ScoringMode.HUMAN, person_cluster_id="p_abc"
        )
        body = client.client.search.call_args.kwargs["body"]
        filters = body["query"]["bool"]["filter"]
        assert any(
            f.get("term", {}).get("people_cluster_ids") == "p_abc" for f in filters
        )

    async def test_product_mode_excludes_people_via_script(self):
        client = _mock_scene_client()
        selector = AutoShortsSelector(client)
        await selector.fetch_candidates(uuid4(), "vid", ScoringMode.PRODUCT)
        body = client.client.search.call_args.kwargs["body"]
        must_not = body["query"]["bool"]["must_not"]
        # Painless script that drops scenes with people_cluster_ids non-empty
        scripts = [m.get("script", {}).get("script", {}).get("source", "") for m in must_not]
        assert any("people_cluster_ids" in s and "size()" in s for s in scripts)

    async def test_product_mode_requires_product_signals(self):
        client = _mock_scene_client()
        selector = AutoShortsSelector(client)
        await selector.fetch_candidates(uuid4(), "vid", ScoringMode.PRODUCT)
        body = client.client.search.call_args.kwargs["body"]
        filters = body["query"]["bool"]["filter"]
        # At least one filter is a bool/should requiring product_tags or product_entities
        assert any(
            "should" in f.get("bool", {}) and f["bool"].get("minimum_should_match") == 1
            for f in filters
        )

    async def test_query_uses_alias_not_concrete_index(self):
        client = _mock_scene_client()
        selector = AutoShortsSelector(client)
        await selector.fetch_candidates(uuid4(), "vid", ScoringMode.BOTH)
        assert client.client.search.call_args.kwargs["index"] == "heimdex_scenes"

    async def test_query_caps_size_at_max_scenes(self):
        client = _mock_scene_client()
        selector = AutoShortsSelector(client)
        await selector.fetch_candidates(uuid4(), "vid", ScoringMode.BOTH)
        body = client.client.search.call_args.kwargs["body"]
        assert body["size"] == 1000

    async def test_results_parsed_into_scene_documents(self):
        client = _mock_scene_client(
            hits=[
                _scene_hit(
                    "vid_scene_000",
                    index=0,
                    start_ms=0,
                    end_ms=10_000,
                    people_cluster_ids=["p1"],
                ),
                _scene_hit(
                    "vid_scene_001",
                    index=1,
                    start_ms=10_000,
                    end_ms=20_000,
                ),
            ]
        )
        selector = AutoShortsSelector(client)
        scenes = await selector.fetch_candidates(uuid4(), "vid", ScoringMode.BOTH)
        assert len(scenes) == 2
        assert scenes[0].scene_id == "vid_scene_000"
        assert scenes[0].people_cluster_ids == ["p1"]

    async def test_malformed_scene_skipped_does_not_break_request(self):
        client = _mock_scene_client(
            hits=[
                {"_id": "org:bad", "_source": {"scene_id": "no_index_field"}},  # invalid
                _scene_hit("vid_scene_000", index=0, start_ms=0, end_ms=10_000),
            ]
        )
        selector = AutoShortsSelector(client)
        scenes = await selector.fetch_candidates(uuid4(), "vid", ScoringMode.BOTH)
        # Bad doc dropped, good doc kept
        assert len(scenes) == 1
        assert scenes[0].scene_id == "vid_scene_000"

    async def test_empty_results(self):
        client = _mock_scene_client(hits=[])
        selector = AutoShortsSelector(client)
        scenes = await selector.fetch_candidates(uuid4(), "vid", ScoringMode.BOTH)
        assert scenes == []
