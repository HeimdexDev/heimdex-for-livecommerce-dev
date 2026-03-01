"""Tests for export hashing (deterministic cache keys)."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any, Protocol

import pytest


class _ComputeHashFn(Protocol):
    def __call__(
        self,
        *,
        org_id: str,
        clips: list[dict[str, Any]],
        include_markers: bool,
        include_transcript_markers: bool,
        clip_gap_ms: int,
    ) -> str: ...


MODULE_PATH = (
    Path(__file__).resolve().parents[4]
    / "services"
    / "api"
    / "app"
    / "modules"
    / "export"
    / "hashing.py"
)
SPEC = spec_from_file_location("hashing", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
_mod = module_from_spec(SPEC)
SPEC.loader.exec_module(_mod)

compute_export_hash: _ComputeHashFn = _mod.compute_export_hash  # type: ignore[assignment]


_BASE_CLIPS: list[dict[str, Any]] = [
    {"scene_id": "s1", "video_id": "gd_v1", "start_ms": 0, "end_ms": 5000},
    {"scene_id": "s2", "video_id": "gd_v2", "start_ms": 1000, "end_ms": 6000},
]

_BASE_KWARGS: dict[str, Any] = {
    "org_id": "org-123",
    "clips": _BASE_CLIPS,
    "include_markers": True,
    "include_transcript_markers": False,
    "clip_gap_ms": 0,
}


def test_deterministic_same_input():
    """Same inputs always produce the same hash."""
    h1 = compute_export_hash(**_BASE_KWARGS)
    h2 = compute_export_hash(**_BASE_KWARGS)
    assert h1 == h2


def test_hash_length_is_16():
    """Hash is always a 16-character hex string."""
    h = compute_export_hash(**_BASE_KWARGS)
    assert len(h) == 16
    assert all(c in "0123456789abcdef" for c in h)


def test_different_org_id_produces_different_hash():
    h1 = compute_export_hash(**_BASE_KWARGS)
    h2 = compute_export_hash(**{**_BASE_KWARGS, "org_id": "org-999"})
    assert h1 != h2


def test_different_clips_produce_different_hash():
    different_clips = [
        {"scene_id": "s99", "video_id": "gd_v99", "start_ms": 0, "end_ms": 1000},
    ]
    h1 = compute_export_hash(**_BASE_KWARGS)
    h2 = compute_export_hash(**{**_BASE_KWARGS, "clips": different_clips})
    assert h1 != h2


def test_different_markers_produce_different_hash():
    h1 = compute_export_hash(**_BASE_KWARGS)
    h2 = compute_export_hash(**{**_BASE_KWARGS, "include_markers": False})
    assert h1 != h2


def test_different_transcript_markers_produce_different_hash():
    h1 = compute_export_hash(**_BASE_KWARGS)
    h2 = compute_export_hash(**{**_BASE_KWARGS, "include_transcript_markers": True})
    assert h1 != h2


def test_different_gap_ms_produces_different_hash():
    h1 = compute_export_hash(**_BASE_KWARGS)
    h2 = compute_export_hash(**{**_BASE_KWARGS, "clip_gap_ms": 1000})
    assert h1 != h2


def test_clip_order_does_not_matter():
    """Clips are sorted by scene_id, so reordering the input list gives the same hash."""
    reversed_clips = list(reversed(_BASE_CLIPS))
    h1 = compute_export_hash(**_BASE_KWARGS)
    h2 = compute_export_hash(**{**_BASE_KWARGS, "clips": reversed_clips})
    assert h1 == h2


def test_extra_clip_fields_are_ignored():
    """Only scene_id, video_id, start_ms, end_ms are used; extra fields are stripped."""
    clips_with_extras = [
        {**c, "label": "some label", "transcript_raw": "blah", "keyword_tags": ["tag1"]}
        for c in _BASE_CLIPS
    ]
    h1 = compute_export_hash(**_BASE_KWARGS)
    h2 = compute_export_hash(**{**_BASE_KWARGS, "clips": clips_with_extras})
    assert h1 == h2


def test_empty_clips_list():
    """Empty clips still produce a valid hash."""
    h = compute_export_hash(**{**_BASE_KWARGS, "clips": []})
    assert len(h) == 16