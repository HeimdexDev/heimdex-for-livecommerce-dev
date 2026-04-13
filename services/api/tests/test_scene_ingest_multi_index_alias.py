"""Tests for multi-index alias handling in SceneIngestMixin.

Background: when the scenes alias (heimdex_scenes) points at multiple
backing indices during a migration cutover (e.g. heimdex_scenes_v4 AND
heimdex_scenes_v5), direct mget / bulk operations with a hardcoded
_index silently miss docs that live in the other backing index — and
partial updates silently create duplicates in the wrong index.

These tests verify that mget_scenes, _resolve_doc_indices, and
bulk_partial_update_scenes all correctly route via the alias and use
per-doc _index resolution.

Tests stub the underlying OpenSearch client (no real connections).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.search.scene_ingest import SceneIngestMixin


class _StubMixin(SceneIngestMixin):
    """Minimal test subject that fulfills the SceneIngestMixin contract.

    The real SceneSearchClient inherits SceneIngestMixin via
    scene_client.py:9. Here we compose the mixin with a MagicMock client
    and settings so we can assert OpenSearch calls without running them.
    """

    def __init__(self, alias_name: str = "heimdex_scenes", index_name: str = "heimdex_scenes_v5"):
        self.alias_name = alias_name
        self.index_name = index_name
        self.client = MagicMock()
        self.client.search = AsyncMock()
        self.client.mget = AsyncMock()
        self.client.bulk = AsyncMock()
        self.settings = MagicMock()
        self.settings.opensearch_bulk_refresh = "true"


def _search_response(hits: list[dict[str, Any]]) -> dict[str, Any]:
    return {"hits": {"hits": hits}}


def _hit(doc_id: str, index: str, source: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "_id": doc_id,
        "_index": index,
        "_source": source or {"scene_id": doc_id.split(":", 1)[1]},
    }


# ─── mget_scenes ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mget_scenes_uses_ids_query_against_alias():
    """mget_scenes must hit the alias with an ids query — not a direct
    mget — so it works across multi-index aliases."""

    mixin = _StubMixin()
    mixin.client.search.return_value = _search_response([
        _hit("org1:scene_a", "heimdex_scenes_v5"),
    ])

    result = await mixin.mget_scenes(["org1:scene_a"])

    # Must have queried via search (not mget)
    mixin.client.search.assert_awaited_once()
    mixin.client.mget.assert_not_called()

    call_kwargs = mixin.client.search.await_args.kwargs
    assert call_kwargs["index"] == "heimdex_scenes"  # alias, not index_name
    body = call_kwargs["body"]
    assert body["query"] == {"ids": {"values": ["org1:scene_a"]}}
    assert body["_source"] is True

    assert result == {"org1:scene_a": {"scene_id": "scene_a"}}


@pytest.mark.asyncio
async def test_mget_scenes_returns_docs_from_multiple_backing_indices():
    """The alias has docs split across v4 and v5. mget_scenes returns
    both as if they live in a single logical index."""

    mixin = _StubMixin()
    mixin.client.search.return_value = _search_response([
        _hit("org1:scene_in_v4", "heimdex_scenes_v4", {"scene_id": "scene_in_v4"}),
        _hit("org1:scene_in_v5", "heimdex_scenes_v5", {"scene_id": "scene_in_v5"}),
    ])

    result = await mixin.mget_scenes(["org1:scene_in_v4", "org1:scene_in_v5"])

    assert len(result) == 2
    assert result["org1:scene_in_v4"]["scene_id"] == "scene_in_v4"
    assert result["org1:scene_in_v5"]["scene_id"] == "scene_in_v5"


@pytest.mark.asyncio
async def test_mget_scenes_empty_input():
    mixin = _StubMixin()
    result = await mixin.mget_scenes([])
    assert result == {}
    mixin.client.search.assert_not_called()


@pytest.mark.asyncio
async def test_mget_scenes_missing_docs_not_in_result():
    """Docs that don't exist in any backing index are omitted from the
    returned dict (no sentinel values)."""

    mixin = _StubMixin()
    mixin.client.search.return_value = _search_response([
        _hit("org1:scene_real", "heimdex_scenes_v5"),
    ])

    result = await mixin.mget_scenes(["org1:scene_real", "org1:scene_missing"])
    assert "org1:scene_real" in result
    assert "org1:scene_missing" not in result


# ─── _resolve_doc_indices ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_doc_indices_maps_each_doc_to_its_index():
    mixin = _StubMixin()
    mixin.client.search.return_value = _search_response([
        _hit("org1:a", "heimdex_scenes_v4"),
        _hit("org1:b", "heimdex_scenes_v5"),
        _hit("org1:c", "heimdex_scenes_v4"),
    ])

    m = await mixin._resolve_doc_indices(["org1:a", "org1:b", "org1:c"])
    assert m == {
        "org1:a": "heimdex_scenes_v4",
        "org1:b": "heimdex_scenes_v5",
        "org1:c": "heimdex_scenes_v4",
    }
    call_kwargs = mixin.client.search.await_args.kwargs
    assert call_kwargs["index"] == "heimdex_scenes"
    assert call_kwargs["body"]["_source"] is False


@pytest.mark.asyncio
async def test_resolve_doc_indices_omits_missing_docs():
    """Missing doc_ids (not yet indexed) are absent from the map —
    callers should fall back to self.index_name for new writes."""
    mixin = _StubMixin()
    mixin.client.search.return_value = _search_response([
        _hit("org1:a", "heimdex_scenes_v5"),
    ])
    m = await mixin._resolve_doc_indices(["org1:a", "org1:new_doc"])
    assert m == {"org1:a": "heimdex_scenes_v5"}


@pytest.mark.asyncio
async def test_resolve_doc_indices_empty_input():
    mixin = _StubMixin()
    m = await mixin._resolve_doc_indices([])
    assert m == {}
    mixin.client.search.assert_not_called()


# ─── bulk_partial_update_scenes ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_partial_update_routes_per_doc_index():
    """Each update action must target the actual backing index of its
    doc, not self.index_name, when the doc already exists."""

    mixin = _StubMixin()
    mixin.client.search.return_value = _search_response([
        _hit("org1:live_in_v4", "heimdex_scenes_v4"),
        _hit("org1:live_in_v5", "heimdex_scenes_v5"),
    ])

    updates = [
        ("org1:live_in_v4", {"scene_caption": "A"}),
        ("org1:live_in_v5", {"scene_caption": "B"}),
    ]
    await mixin.bulk_partial_update_scenes(updates)

    # _resolve_doc_indices search
    mixin.client.search.assert_awaited_once()

    # bulk body checks
    mixin.client.bulk.assert_awaited_once()
    bulk_body = mixin.client.bulk.await_args.kwargs["body"]
    assert len(bulk_body) == 4  # 2 action/doc pairs

    action0 = bulk_body[0]
    assert action0["update"]["_index"] == "heimdex_scenes_v4"
    assert action0["update"]["_id"] == "org1:live_in_v4"
    assert bulk_body[1] == {"doc": {"scene_caption": "A"}}

    action1 = bulk_body[2]
    assert action1["update"]["_index"] == "heimdex_scenes_v5"
    assert action1["update"]["_id"] == "org1:live_in_v5"
    assert bulk_body[3] == {"doc": {"scene_caption": "B"}}


@pytest.mark.asyncio
async def test_bulk_partial_update_falls_back_to_index_name_for_unknown_docs():
    """A doc not found in any backing index (e.g. being written for the
    first time) should route to self.index_name."""

    mixin = _StubMixin()
    mixin.client.search.return_value = _search_response([])  # nothing found

    updates = [("org1:brand_new", {"scene_caption": "fresh"})]
    await mixin.bulk_partial_update_scenes(updates)

    bulk_body = mixin.client.bulk.await_args.kwargs["body"]
    assert bulk_body[0]["update"]["_index"] == "heimdex_scenes_v5"  # self.index_name


@pytest.mark.asyncio
async def test_bulk_partial_update_empty_input():
    mixin = _StubMixin()
    await mixin.bulk_partial_update_scenes([])
    mixin.client.search.assert_not_called()
    mixin.client.bulk.assert_not_called()


@pytest.mark.asyncio
async def test_bulk_partial_update_single_index_alias_still_works():
    """Regression: staging has a single-index alias. The fix must not
    break that case (all docs resolved to v5)."""

    mixin = _StubMixin()
    mixin.client.search.return_value = _search_response([
        _hit("org1:a", "heimdex_scenes_v5"),
        _hit("org1:b", "heimdex_scenes_v5"),
    ])

    updates = [
        ("org1:a", {"scene_caption": "A"}),
        ("org1:b", {"scene_caption": "B"}),
    ]
    await mixin.bulk_partial_update_scenes(updates)

    bulk_body = mixin.client.bulk.await_args.kwargs["body"]
    assert bulk_body[0]["update"]["_index"] == "heimdex_scenes_v5"
    assert bulk_body[2]["update"]["_index"] == "heimdex_scenes_v5"
