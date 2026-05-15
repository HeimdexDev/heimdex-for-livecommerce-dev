"""Tests for the StitchPlan → CompositionSpec adapter.

The most important test in this file is
:func:`test_dict_shape_matches_worker` — it pins down the equivalence
between this API-side helper and the worker's
``_build_composition_spec`` so the two copies (which can't share a
common lib — see ``children/composition.py`` for the rationale)
won't silently drift.
"""

from __future__ import annotations

import pytest

from app.lib.product_track.alignment import AnnotatedWindow
from app.lib.product_track.stitching import StitchPlan
from app.lib.product_track.subset_selector import ScoredWindow
from app.modules.shorts_auto_product.children.composition import (
    build_composition_spec_from_stitch_plan,
)


def _make_window(
    *,
    scene_id: str,
    start_ms: int,
    end_ms: int,
    score: float = 0.7,
) -> ScoredWindow:
    """Synthetic ScoredWindow with sane field defaults.

    Adapter only cares about ``window.scene_id`` /
    ``window.window_start_ms`` / ``window.window_end_ms``; every
    other field gets a placeholder so the dataclass constructor
    succeeds.
    """
    return ScoredWindow(
        window=AnnotatedWindow(
            scene_id=scene_id,
            window_start_ms=start_ms,
            window_end_ms=end_ms,
            avg_bbox_area_pct=0.25,
            avg_confidence=0.85,
            peak_confidence=0.92,
            frame_count=int((end_ms - start_ms) / 200),  # 5fps cadence
            rejected_reason=None,
            has_narration_mention=False,
            has_ocr_overlap=False,
        ),
        composite_score=score,
        score_components={},
    )


def _make_plan(*windows: ScoredWindow) -> StitchPlan:
    total_ms = sum(
        s.window.window_end_ms - s.window.window_start_ms for s in windows
    )
    return StitchPlan(
        duration_target_sec=30,
        duration_actual_ms=total_ms,
        windows=list(windows),
        scorer_version="v1.0",
        subset_picker_version="v1.0",
    )


# ---------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------


def test_single_window_yields_one_scene_clip_at_origin() -> None:
    plan = _make_plan(
        _make_window(scene_id="gd_abc_scene_005", start_ms=10_000, end_ms=18_000),
    )
    spec = build_composition_spec_from_stitch_plan(
        plan=plan, os_video_id="gd_abc",
    )
    assert len(spec.scene_clips) == 1
    clip = spec.scene_clips[0]
    assert clip.scene_id == "gd_abc_scene_005"
    assert clip.video_id == "gd_abc"
    assert clip.source_type == "gdrive"
    assert clip.start_ms == 10_000
    assert clip.end_ms == 18_000
    assert clip.timeline_start_ms == 0  # first clip starts at the origin
    assert clip.volume == 1.0


def test_multiple_windows_placed_back_to_back_chronologically() -> None:
    plan = _make_plan(
        _make_window(scene_id="s1", start_ms=0,       end_ms=4_000),   # 4s
        _make_window(scene_id="s2", start_ms=10_000,  end_ms=15_000),  # 5s
        _make_window(scene_id="s3", start_ms=30_000,  end_ms=33_000),  # 3s
    )
    spec = build_composition_spec_from_stitch_plan(
        plan=plan, os_video_id="gd_xyz",
    )
    clips = spec.scene_clips
    assert [c.scene_id for c in clips] == ["s1", "s2", "s3"]
    # Each clip's timeline position = sum of prior clip durations.
    assert clips[0].timeline_start_ms == 0
    assert clips[1].timeline_start_ms == 4_000        # after s1's 4s
    assert clips[2].timeline_start_ms == 4_000 + 5_000  # after s1+s2 = 9s
    # Source ranges remain absolute (NOT timeline-relative).
    assert (clips[1].start_ms, clips[1].end_ms) == (10_000, 15_000)


def test_video_id_propagates_to_every_clip() -> None:
    plan = _make_plan(
        _make_window(scene_id="s1", start_ms=0, end_ms=2_000),
        _make_window(scene_id="s2", start_ms=5_000, end_ms=8_000),
    )
    spec = build_composition_spec_from_stitch_plan(
        plan=plan, os_video_id="gd_video123",
    )
    assert all(c.video_id == "gd_video123" for c in spec.scene_clips)


def test_default_subtitles_overlays_transitions_filled_by_contract() -> None:
    """The adapter only sets ``scene_clips``; the contracts default_factory
    populates ``output`` (9:16 720p), ``subtitles=[]``, ``overlays=[]``,
    ``transitions=[]``. Verify those defaults survive the adapter so
    downstream rendering sees a valid shape."""
    plan = _make_plan(_make_window(scene_id="s1", start_ms=0, end_ms=1_000))
    spec = build_composition_spec_from_stitch_plan(
        plan=plan, os_video_id="gd_x",
    )
    assert spec.subtitles == []
    assert spec.overlays == []
    assert spec.transitions == []
    assert spec.output is not None  # default OutputSpec instance
    assert spec.title is None
    assert spec.version == 1


# ---------------------------------------------------------------------
# defensive guard
# ---------------------------------------------------------------------


def test_empty_plan_raises_value_error() -> None:
    """The contracts validator rejects ``scene_clips=[]`` with a
    confusing pydantic ValidationError. The adapter pre-empts that
    with a clearer ValueError so the runner's stack trace points
    at the actual missing-windows condition."""
    plan = _make_plan()  # no windows
    with pytest.raises(ValueError, match="stitch plan has no windows"):
        build_composition_spec_from_stitch_plan(
            plan=plan, os_video_id="gd_x",
        )


# ---------------------------------------------------------------------
# divergence guard — equivalence with worker's _build_composition_spec
# ---------------------------------------------------------------------


def test_dict_shape_matches_worker() -> None:
    """**Cross-codebase invariant.**

    The worker's ``services/product-track-worker/src/tasks/track.py::_build_composition_spec``
    and this adapter MUST produce equivalent output for identical
    inputs. We can't import the worker (different service boundary),
    so this test snapshots the expected dict shape inline. If this
    diff stops matching, either:

      * the worker changed its mapping → mirror the change here, or
      * the contract changed shape → bump both call sites.

    Either way, fix the divergence at the source — DO NOT loosen the
    snapshot to make the test pass.
    """
    plan = _make_plan(
        _make_window(scene_id="gd_video_scene_001", start_ms=1_000, end_ms=4_000),
        _make_window(scene_id="gd_video_scene_007", start_ms=20_000, end_ms=22_500),
    )
    spec = build_composition_spec_from_stitch_plan(
        plan=plan, os_video_id="gd_video",
    )
    actual_clips = [
        # Restrict to the keys the worker emits — the adapter may
        # additionally fill in crop_x/y/w/h with their contract
        # defaults, which is fine; the worker omits them and the
        # contracts default_factory fills the same values, so the
        # rendered output is identical regardless.
        {
            "scene_id": c.scene_id,
            "video_id": c.video_id,
            "source_type": c.source_type,
            "start_ms": c.start_ms,
            "end_ms": c.end_ms,
            "timeline_start_ms": c.timeline_start_ms,
            "volume": c.volume,
        }
        for c in spec.scene_clips
    ]
    expected_clips = [
        {
            "scene_id": "gd_video_scene_001",
            "video_id": "gd_video",
            "source_type": "gdrive",
            "start_ms": 1_000,
            "end_ms": 4_000,
            "timeline_start_ms": 0,
            "volume": 1.0,
        },
        {
            "scene_id": "gd_video_scene_007",
            "video_id": "gd_video",
            "source_type": "gdrive",
            "start_ms": 20_000,
            "end_ms": 22_500,
            "timeline_start_ms": 3_000,  # after the first clip's 3s
            "volume": 1.0,
        },
    ]
    assert actual_clips == expected_clips
