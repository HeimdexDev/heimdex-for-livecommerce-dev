"""Tests for the Phase 4 single-product round-robin picker.

Covers the catalog-selection layer ONLY. Window-level picking is
exercised by the vendored ``app.lib.product_track`` chain's own
tests upstream (and indirectly by the runner integration tests
that ship in PR #6 commit 4).
"""

from __future__ import annotations

from uuid import UUID

import pytest

from app.modules.shorts_auto_product.children.picker import (
    CatalogPick,
    SingleProductSubsetPicker,
    pick_catalog_for_shorts_index,
)


# Fixed UUIDs so the sorted ordering is predictable and assertions
# can speak in terms of "first sorted catalog" without re-running
# the sort in each test.
CAT_A = UUID("00000000-0000-0000-0000-0000000000a1")
CAT_B = UUID("00000000-0000-0000-0000-0000000000b2")
CAT_C = UUID("00000000-0000-0000-0000-0000000000c3")
SORTED_3 = [CAT_A, CAT_B, CAT_C]


# ---------------------------------------------------------------------
# pick_catalog_for_shorts_index — pure helper
# ---------------------------------------------------------------------


def test_round_robin_distributes_5_shorts_across_3_products() -> None:
    """The headline plan §7.1 example: 5 shorts of 3 products map to
    [c1, c2, c3, c1, c2]."""
    picks = [
        pick_catalog_for_shorts_index(catalog_ids=SORTED_3, shorts_index=i)
        for i in (1, 2, 3, 4, 5)
    ]
    assert picks == [CAT_A, CAT_B, CAT_C, CAT_A, CAT_B]


def test_single_product_means_every_short_picks_it() -> None:
    """N shorts × 1 product = N copies of that product."""
    for i in range(1, 11):
        assert (
            pick_catalog_for_shorts_index(
                catalog_ids=[CAT_A], shorts_index=i,
            )
            == CAT_A
        )


def test_unsorted_input_yields_sorted_distribution() -> None:
    """Input order must NOT affect output — two replicas with the
    same catalog set but different iteration order MUST produce
    identical (shorts_index → catalog) mappings."""
    forward = [
        pick_catalog_for_shorts_index(
            catalog_ids=[CAT_A, CAT_B, CAT_C], shorts_index=i,
        )
        for i in (1, 2, 3)
    ]
    reverse = [
        pick_catalog_for_shorts_index(
            catalog_ids=[CAT_C, CAT_B, CAT_A], shorts_index=i,
        )
        for i in (1, 2, 3)
    ]
    assert forward == reverse == SORTED_3


def test_set_input_works_and_dedupes() -> None:
    """Accepting an Iterable means callers can pass a set — must
    still be deterministic via the internal sort."""
    picks = [
        pick_catalog_for_shorts_index(
            catalog_ids={CAT_C, CAT_A, CAT_B, CAT_A},  # CAT_A duplicated
            shorts_index=i,
        )
        for i in (1, 2, 3, 4)
    ]
    # Dedup → 3 catalogs → round-robin wraps at index 4.
    assert picks == [CAT_A, CAT_B, CAT_C, CAT_A]


def test_empty_catalog_ids_raises() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        pick_catalog_for_shorts_index(catalog_ids=[], shorts_index=1)


def test_zero_or_negative_shorts_index_raises() -> None:
    """Migration 052's CHECK enforces shorts_index >= 1; the picker
    rejects out-of-range values too so a buggy fan-out hook can't
    silently misbehave."""
    for bad in (0, -1, -100):
        with pytest.raises(ValueError, match="shorts_index must be >= 1"):
            pick_catalog_for_shorts_index(catalog_ids=SORTED_3, shorts_index=bad)


def test_large_shorts_index_wraps() -> None:
    """No upper bound on shorts_index in the helper itself — the
    DB CHECK caps requested_count <= 50, but the helper stays pure
    and just wraps modulo."""
    # shorts_index=100 with 3 products → (100-1) % 3 = 99 % 3 = 0
    # → first sorted catalog.
    assert (
        pick_catalog_for_shorts_index(
            catalog_ids=SORTED_3, shorts_index=100,
        )
        == CAT_A
    )


# ---------------------------------------------------------------------
# SingleProductSubsetPicker — class wrapper
# ---------------------------------------------------------------------


def test_picker_class_returns_catalog_pick_with_count() -> None:
    """The class wrapper enriches the bare UUID with the candidate
    set size so the runner's logging doesn't recompute it."""
    picker = SingleProductSubsetPicker()
    pick = picker.pick_catalog(catalog_ids=SORTED_3, shorts_index=2)
    assert isinstance(pick, CatalogPick)
    assert pick.catalog_entry_id == CAT_B
    assert pick.candidates_count == 3


def test_picker_class_dedupes_in_count() -> None:
    """Duplicates in the input must not inflate ``candidates_count``."""
    picker = SingleProductSubsetPicker()
    pick = picker.pick_catalog(
        catalog_ids=[CAT_A, CAT_A, CAT_B], shorts_index=1,
    )
    assert pick.candidates_count == 2


def test_picker_class_version_string_is_stable() -> None:
    """The runner persists ``VERSION`` on the parent's
    ``picker_version`` column for replay determinism. Bumping it
    should be a deliberate code change, not a side effect — assert
    the literal so a refactor doesn't silently shift the value."""
    assert SingleProductSubsetPicker.VERSION == "single-rr-v1"


def test_picker_class_consistent_with_helper() -> None:
    """The class is a thin wrapper — the chosen catalog must match
    the bare helper's output for any well-formed input."""
    picker = SingleProductSubsetPicker()
    for shorts_index in range(1, 11):
        helper = pick_catalog_for_shorts_index(
            catalog_ids=SORTED_3, shorts_index=shorts_index,
        )
        wrapped = picker.pick_catalog(
            catalog_ids=SORTED_3, shorts_index=shorts_index,
        )
        assert wrapped.catalog_entry_id == helper
