"""Selector tests: OS query construction per mode + result parsing."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

shorts_scorer = pytest.importorskip(
    "heimdex_media_contracts.shorts.scorer",
    reason="cross-package contract test requires heimdex-media-contracts shorts scorer",
)

pytestmark = pytest.mark.contract

from app.modules.shorts_auto.selector import (
    AutoShortsSelector,
    _derive_index_from_scene_id,
)

ScoringMode = shorts_scorer.ScoringMode


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
        result = await selector.fetch_candidates(uuid4(), "vid", ScoringMode.BOTH)
        assert len(result.scenes) == 2
        assert result.scenes[0].scene_id == "vid_scene_000"
        assert result.scenes[0].people_cluster_ids == ["p1"]

    async def test_malformed_scene_skipped_does_not_break_request(self):
        client = _mock_scene_client(
            hits=[
                {"_id": "org:bad", "_source": {"scene_id": "no_index_field"}},  # invalid
                _scene_hit("vid_scene_000", index=0, start_ms=0, end_ms=10_000),
            ]
        )
        selector = AutoShortsSelector(client)
        result = await selector.fetch_candidates(uuid4(), "vid", ScoringMode.BOTH)
        # Bad doc dropped, good doc kept
        assert len(result.scenes) == 1
        assert result.scenes[0].scene_id == "vid_scene_000"

    async def test_empty_results(self):
        client = _mock_scene_client(hits=[])
        selector = AutoShortsSelector(client)
        result = await selector.fetch_candidates(uuid4(), "vid", ScoringMode.BOTH)
        assert result.scenes == []
        assert result.speaker_transcripts == {}

    async def test_source_fields_include_speaker_transcript(self):
        """Regression guard: speaker_transcript must be requested from OS
        so the auto-shorts inspector script panel has speaker turns to
        render. Removing it from _SOURCE_FIELDS would silently degrade
        the script panel to non-diarized fallback.
        """
        client = _mock_scene_client()
        selector = AutoShortsSelector(client)
        await selector.fetch_candidates(uuid4(), "vid", ScoringMode.BOTH)
        body = client.client.search.call_args.kwargs["body"]
        assert "speaker_transcript" in body["_source"]

    async def test_speaker_transcript_extracted_when_present(self):
        client = _mock_scene_client(
            hits=[
                _scene_hit(
                    "vid_scene_000",
                    index=0,
                    start_ms=0,
                    end_ms=10_000,
                    speaker_transcript="A 0:00 안녕하세요\nB 0:03 반갑습니다",
                ),
                _scene_hit(
                    "vid_scene_001",
                    index=1,
                    start_ms=10_000,
                    end_ms=20_000,
                    # no speaker_transcript field at all
                ),
                _scene_hit(
                    "vid_scene_002",
                    index=2,
                    start_ms=20_000,
                    end_ms=30_000,
                    speaker_transcript="   ",  # whitespace-only — should be skipped
                ),
            ]
        )
        selector = AutoShortsSelector(client)
        result = await selector.fetch_candidates(uuid4(), "vid", ScoringMode.BOTH)
        assert len(result.scenes) == 3
        assert result.speaker_transcripts == {
            "vid_scene_000": "A 0:00 안녕하세요\nB 0:03 반갑습니다",
        }


class TestDeriveIndexFromSceneId:
    """Scene indexing in OpenSearch doesn't store `index` separately —
    the value is embedded in the `_scene_NNN` suffix of scene_id. Selector
    derives it so SceneDocument(**src) doesn't raise on a missing field.
    Bug surfaced 2026-04-24 on staging after the devorg full reprocess
    produced scenes with the standard suffix format but no separate
    ``index`` column in the OS mapping.
    """

    def test_extracts_index_from_standard_format(self):
        assert _derive_index_from_scene_id("gd_abc123_scene_042") == 42

    def test_extracts_zero_padded_index(self):
        assert _derive_index_from_scene_id("gd_abc123_scene_000") == 0

    def test_extracts_large_index(self):
        assert _derive_index_from_scene_id("gd_abc123_scene_999") == 999

    def test_handles_underscore_in_video_id(self):
        assert _derive_index_from_scene_id("gd_vid_with_scene_in_name_scene_007") == 7

    def test_returns_none_on_missing_suffix(self):
        assert _derive_index_from_scene_id("gd_abc123") is None

    def test_returns_none_on_non_numeric_suffix(self):
        assert _derive_index_from_scene_id("gd_abc_scene_abc") is None

    def test_returns_none_on_none_input(self):
        assert _derive_index_from_scene_id(None) is None

    def test_returns_none_on_non_string_input(self):
        assert _derive_index_from_scene_id(42) is None


@pytest.mark.asyncio
async def test_selector_survives_scenes_missing_index_field():
    """Repro of the staging 2026-04-24 bug: OS scenes come back without
    ``index`` but with a well-formed scene_id. Selector must derive index
    and NOT log parse_failed for every scene.
    """
    hits = [
        {
            "_source": {
                "scene_id": "gd_005f45675035f730_scene_042",
                "video_id": "gd_005f45675035f730",
                # NO ``index`` field — the bug trigger
                "start_ms": 42_000,
                "end_ms": 57_000,
                "keyframe_timestamp_ms": 50_000,
                "scene_caption": "",
                "transcript_raw": "",
            }
        }
    ]
    client = _mock_scene_client(hits=hits)
    selector = AutoShortsSelector(client)
    result = await selector.fetch_candidates(uuid4(), "gd_005f45675035f730", ScoringMode.BOTH)
    assert len(result.scenes) == 1
    assert result.scenes[0].index == 42
