"""Tests for the scene_id parsing helper."""

from __future__ import annotations

import pytest

from app.modules.shorts_auto_product.children.scene_id_utils import (
    os_video_id_from_scene_id,
)


def test_video_scene_id_yields_drive_prefix() -> None:
    assert (
        os_video_id_from_scene_id("gd_abc123_scene_005") == "gd_abc123"
    )


def test_image_scene_id_yields_drive_prefix() -> None:
    """Image scene_ids end in ``_scene_000`` (single scene per image)
    per drive-worker/src/tasks/process.py:112; the helper must work
    for both surfaces."""
    assert os_video_id_from_scene_id("gd_xyz_scene_000") == "gd_xyz"


def test_underscores_in_video_id_preserved() -> None:
    """Drive ids can carry underscores (``gd_abc_def``); rsplit on
    the LAST ``_scene_`` is the right semantics so internal
    underscores survive."""
    assert (
        os_video_id_from_scene_id("gd_abc_def_scene_010")
        == "gd_abc_def"
    )


def test_video_id_containing_substring_scene() -> None:
    """Adversarial: a video_id could in principle contain the
    literal substring ``_scene_`` (e.g., a future `scene_*`-style
    naming). rsplit with maxsplit=1 picks the LAST occurrence, so
    the trailing ``_scene_NNN`` is what's stripped — the prefix
    keeps any earlier ``_scene_`` instance intact."""
    assert (
        os_video_id_from_scene_id("gd_my_scene_video_scene_007")
        == "gd_my_scene_video"
    )


def test_empty_string_raises() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        os_video_id_from_scene_id("")


def test_missing_sentinel_raises() -> None:
    """No ``_scene_`` infix → can't parse. Indicates a corrupted DB
    row or a scene_id-format change."""
    with pytest.raises(ValueError, match="convention"):
        os_video_id_from_scene_id("gd_no_separator_at_all")


def test_empty_prefix_raises() -> None:
    """Trailing ``_scene_NNN`` without a video_id prefix is ill-formed."""
    with pytest.raises(ValueError, match="convention"):
        os_video_id_from_scene_id("_scene_001")
