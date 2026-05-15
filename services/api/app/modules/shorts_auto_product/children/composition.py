"""``StitchPlan`` → :class:`CompositionSpec` adapter for the wizard runner.

## Why this lives here, not lifted to a shared lib

There is no third-party package both the API and
``services/product-track-worker/`` can import from. The vendored
``app/lib/product_track/`` is API-only; ``services/product-track-worker/``
is a fully isolated container that doesn't ship API code.
``heimdex_media_contracts`` defines :class:`CompositionSpec` but does
not (and should not) know about ``StitchPlan`` — that is a pipelines
type. Adding a contracts→pipelines reverse dependency to host this
adapter would invert the layering.

So the worker keeps its own copy of the same mapping in
``services/product-track-worker/src/tasks/track.py::_build_composition_spec``
and the API runner imports this module. The two implementations
must produce equivalent output for identical inputs (the ``CompositionSpec``
contract is the spec); the equivalence test in
``tests/test_composition_adapter.py`` snapshots the dict shape both
sides emit.

## What the adapter does

Each ``StitchPlan.windows[i]`` (a :class:`ScoredWindow` with an inner
:class:`AnnotatedWindow` carrying ``scene_id`` + ``window_start_ms`` +
``window_end_ms``) becomes one :class:`SceneClipSpec`. Clips are
placed back-to-back chronologically on the composition timeline.

* Source type is hard-coded ``gdrive`` (livecommerce only ingests
  via Drive in v1; future Drive sources need a per-source switch).
* ``volume=1.0``, no transitions, no subtitles — hard cuts only,
  matching plan §6.2 step 8 v1 contract.
* ``output`` is left to ``CompositionSpec``'s default_factory which
  produces 9:16 vertical 720p mp4 — the v1 product-mode shorts UX.

## Empty-plan guard

The contracts validator rejects ``scene_clips=[]`` (`min_length=1`).
The runner is expected to terminate early with ``_terminate_no_render``
when ``select_subset`` returns nothing — this adapter never sees an
empty plan in the happy path. Defensive: we raise ``ValueError``
with a clear message rather than letting the contracts validator
emit a confusing 422 traceback far from the call site.
"""

from __future__ import annotations

from heimdex_media_contracts.composition.schemas import (
    CompositionSpec,
    SceneClipSpec,
)

from app.lib.product_track.stitching import StitchPlan


def build_composition_spec_from_stitch_plan(
    *,
    plan: StitchPlan,
    os_video_id: str,
) -> CompositionSpec:
    """Convert a :class:`StitchPlan` into a typed :class:`CompositionSpec`.

    ``os_video_id`` is the OpenSearch string id (``gd_abc...``) that
    :class:`SceneClipSpec.video_id` accepts — the same shape
    :class:`RenderJobCreate` already takes. Callers obtain it from the
    parent ``ProductScanJob`` row's ``video_id`` (which the wizard
    persists as the OS string id, not the DriveFile UUID).

    Raises:
        ValueError: ``plan.windows`` is empty. The runner must check
            for this and terminate the child via
            ``complete_tracking(render_job_id=None)`` rather than
            calling this adapter.
    """
    if not plan.windows:
        raise ValueError(
            "stitch plan has no windows — cannot build a CompositionSpec; "
            "caller must terminate the child without a render"
        )

    timeline_cursor_ms = 0
    scene_clips: list[SceneClipSpec] = []
    for scored in plan.windows:
        # ``StitchPlan.windows`` is ``list[ScoredWindow]``; the inner
        # ``ScoredWindow.window`` is the :class:`AnnotatedWindow`
        # with the actual time range.
        window = scored.window
        clip_duration_ms = window.window_end_ms - window.window_start_ms
        scene_clips.append(
            SceneClipSpec(
                scene_id=window.scene_id,
                video_id=os_video_id,
                source_type="gdrive",
                start_ms=window.window_start_ms,
                end_ms=window.window_end_ms,
                timeline_start_ms=timeline_cursor_ms,
                volume=1.0,
                # crop_x/y/w/h default to full-frame (0, 0, 1, 1).
            )
        )
        timeline_cursor_ms += clip_duration_ms

    # output / subtitles / overlays / transitions all use
    # CompositionSpec's default_factory — see contracts/composition/schemas.py.
    return CompositionSpec(scene_clips=scene_clips)
