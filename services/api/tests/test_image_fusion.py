from app.modules.search.fusion import (
    diversify_results,
    RankedItem,
    MAX_CONTENT_TYPE_RATIO,
    _balance_content_types,
)


def _make_item(doc_id: str, video_id: str, content_type: str, score: float) -> RankedItem:
    return RankedItem(
        doc_id=doc_id,
        video_id=video_id,
        source={"content_type": content_type},
        fused_score=score,
        adjusted_score=score,
    )


class TestContentTypeBalancing:
    def test_mixed_search_caps_dominant_type(self):
        items = [
            _make_item(f"v{i}", f"vid_{i}", "video", 1.0 - i * 0.01)
            for i in range(8)
        ] + [
            _make_item(f"i{i}", f"img_{i}", "image", 0.5 - i * 0.01)
            for i in range(2)
        ]

        result = diversify_results(
            items, max_per_video=10, target_count=10,
            content_types=["video", "image"],
        )

        max_allowed = int(10 * MAX_CONTENT_TYPE_RATIO)
        top_slice = result[:max_allowed + 1]
        video_in_top = sum(1 for r in top_slice if r.source.get("content_type") == "video")
        image_in_top = sum(1 for r in top_slice if r.source.get("content_type") == "image")
        assert video_in_top <= max_allowed
        assert image_in_top >= 1
        assert len(result) == 10

    def test_single_type_search_no_balancing(self):
        items = [
            _make_item(f"v{i}", f"vid_{i}", "video", 1.0 - i * 0.01)
            for i in range(10)
        ]

        result = diversify_results(
            items, max_per_video=10, target_count=10,
            content_types=["video"],
        )

        assert len(result) == 10
        assert all(r.source.get("content_type") == "video" for r in result)

    def test_no_content_types_no_balancing(self):
        items = [
            _make_item(f"v{i}", f"vid_{i}", "video", 1.0 - i * 0.01)
            for i in range(10)
        ]

        result = diversify_results(
            items, max_per_video=10, target_count=10,
        )

        assert len(result) == 10

    def test_balanced_input_unchanged(self):
        items = [
            _make_item("v1", "vid_1", "video", 1.0),
            _make_item("i1", "img_1", "image", 0.95),
            _make_item("v2", "vid_2", "video", 0.9),
            _make_item("i2", "img_2", "image", 0.85),
            _make_item("v3", "vid_3", "video", 0.8),
            _make_item("i3", "img_3", "image", 0.75),
        ]

        result = diversify_results(
            items, max_per_video=10, target_count=6,
            content_types=["video", "image"],
        )

        assert len(result) == 6
        video_count = sum(1 for r in result if r.source.get("content_type") == "video")
        image_count = sum(1 for r in result if r.source.get("content_type") == "image")
        assert video_count == 3
        assert image_count == 3

    def test_deferred_items_backfilled(self):
        items = [
            _make_item(f"v{i}", f"vid_{i}", "video", 1.0 - i * 0.01)
            for i in range(10)
        ]

        result = diversify_results(
            items, max_per_video=10, target_count=10,
            content_types=["video", "image"],
        )

        assert len(result) == 10

    def test_empty_list_returns_empty(self):
        result = diversify_results(
            [], max_per_video=10, target_count=10,
            content_types=["video", "image"],
        )
        assert result == []


class TestBalanceContentTypesInternal:
    def test_cap_enforced_at_70_percent(self):
        items = [
            _make_item(f"v{i}", f"vid_{i}", "video", 1.0 - i * 0.01)
            for i in range(9)
        ] + [
            _make_item("i0", "img_0", "image", 0.05),
        ]

        result = _balance_content_types(items, target_count=10)

        first_eight = result[:8]
        video_in_first_eight = sum(1 for r in first_eight if r.source.get("content_type") == "video")
        assert video_in_first_eight == 7
        assert any(r.source.get("content_type") == "image" for r in first_eight)
        assert len(result) == 10

    def test_no_items_dropped(self):
        items = [
            _make_item(f"v{i}", f"vid_{i}", "video", 1.0 - i * 0.01)
            for i in range(8)
        ] + [
            _make_item(f"i{i}", f"img_{i}", "image", 0.1 - i * 0.01)
            for i in range(2)
        ]

        result = _balance_content_types(items, target_count=10)
        assert len(result) == 10

    def test_minority_type_promoted(self):
        items = [
            _make_item(f"v{i}", f"vid_{i}", "video", 1.0 - i * 0.01)
            for i in range(9)
        ] + [
            _make_item("i0", "img_0", "image", 0.05),
        ]

        result = _balance_content_types(items, target_count=10)

        image_idx = next(i for i, r in enumerate(result) if r.source.get("content_type") == "image")
        assert image_idx < 10

    def test_single_item_list(self):
        items = [_make_item("v0", "vid_0", "video", 1.0)]
        result = _balance_content_types(items, target_count=5)
        assert len(result) == 1
