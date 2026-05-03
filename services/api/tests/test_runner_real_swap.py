"""Tests for the wizard child runner's PR #6 real-swap pieces.

What this file covers (allowlist-friendly, <100ms total):

  * The new constructor parameter ``scene_search_client``.
  * The ``_appearance_to_annotated_window`` adapter — heuristic
    ``frame_count`` / ``peak_confidence`` synthesis from DB rows
    that the pipeline lib's :class:`AnnotatedWindow` requires but
    that ``ProductAppearance`` doesn't persist.
  * Module-level integrity (imports, factory wiring).

What this file does NOT cover:

  * End-to-end run of ``_process_child_payload`` — that needs a
    real DB session + render service mock + opensearch fake. The
    fixture surface for a self-contained integration test exceeds
    the allowlist's <300ms budget. Per plan §9.4, the runner's
    full flow is verified on staging by manually triggering a
    wizard scan order and observing children land with
    ``render_job_id`` set on the parent's child rows. Adding the
    integration test post-PR #6 lands at the wizard-frontend tier
    (PR #7 brings tests against a real wizard surface anyway).
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.modules.shorts_auto_product.children.runner import (
    ChildRunner,
    _appearance_to_annotated_window,
    create_child_runner,
)
from app.modules.shorts_auto_product.models import ProductAppearance


# ---------------------------------------------------------------------
# constructor wiring
# ---------------------------------------------------------------------


def _settings_stub():
    """Minimal settings stub — only the fields ChildRunner reads at
    construction. Avoids ``Settings()`` which requires env var
    plumbing."""
    s = MagicMock()
    s.auto_shorts_product_v2_child_runner_max_concurrency = 4
    s.auto_shorts_product_v2_child_runner_poll_seconds = 5
    s.auto_shorts_product_v2_child_runner_enabled = True
    s.auto_shorts_product_v2_child_lease_seconds = 300
    return s


def test_constructor_accepts_scene_search_client() -> None:
    """The PR #6 ctor change adds ``scene_search_client``. Verify
    the parameter is stored verbatim so the runner can hand it to
    :class:`ShortsRenderService` later."""
    fake_search = object()
    runner = ChildRunner(
        settings=_settings_stub(),
        session_factory=MagicMock(),
        scene_search_client=fake_search,
    )
    assert runner.scene_search_client is fake_search


def test_factory_threads_scene_search_client_through() -> None:
    """``create_child_runner`` is what ``app.main:lifespan`` calls.
    Verify it forwards the ctor arg unchanged so a future refactor
    of the factory's signature can't silently drop the OS client."""
    fake_search = object()
    runner = create_child_runner(
        settings=_settings_stub(),
        session_factory=MagicMock(),
        scene_search_client=fake_search,
    )
    assert runner.scene_search_client is fake_search


def test_constructor_default_process_fn_is_real_payload() -> None:
    """When tests don't inject ``process_child_fn``, production code
    runs. Asserting this here so a refactor that flips the default
    to a stub (which would tank prod) is caught at test time."""
    runner = ChildRunner(
        settings=_settings_stub(),
        session_factory=MagicMock(),
        scene_search_client=object(),
    )
    # Bound method comparison: __func__ pulls the underlying function
    # off both sides so we don't compare bound-method identity which
    # can vary across Python versions.
    assert runner._process_child_fn.__func__ is ChildRunner._process_child_payload


# ---------------------------------------------------------------------
# _appearance_to_annotated_window adapter
# ---------------------------------------------------------------------


def _make_appearance(
    *,
    scene_id: str = "gd_abc_scene_005",
    window_start_ms: int = 10_000,
    window_end_ms: int = 18_000,
    avg_bbox_area_pct: float = 0.30,
    avg_confidence: float = 0.85,
    has_narration_mention: bool = True,
    has_ocr_overlap: bool = False,
    rejected_reason: str | None = None,
) -> ProductAppearance:
    """Build a ``ProductAppearance`` ORM instance without hitting the
    DB. The model is a SQLAlchemy declarative; constructing it with
    kwargs sets attributes without persisting.
    """
    return ProductAppearance(
        id=uuid4(),
        catalog_entry_id=uuid4(),
        org_id=uuid4(),
        scene_id=scene_id,
        window_start_ms=window_start_ms,
        window_end_ms=window_end_ms,
        avg_bbox_area_pct=avg_bbox_area_pct,
        avg_confidence=avg_confidence,
        has_narration_mention=has_narration_mention,
        has_ocr_overlap=has_ocr_overlap,
        co_appearing_catalog_entry_ids=[],
        tracker_version="v1.0",
        rejected_reason=rejected_reason,
        created_at=datetime.now(timezone.utc),
    )


def test_adapter_copies_core_fields() -> None:
    appearance = _make_appearance()
    aw = _appearance_to_annotated_window(appearance)
    assert aw.scene_id == "gd_abc_scene_005"
    assert aw.window_start_ms == 10_000
    assert aw.window_end_ms == 18_000
    assert aw.avg_bbox_area_pct == pytest.approx(0.30)
    assert aw.avg_confidence == pytest.approx(0.85)
    assert aw.has_narration_mention is True
    assert aw.has_ocr_overlap is False
    assert aw.rejected_reason is None


def test_adapter_synthesizes_peak_confidence_from_avg() -> None:
    """``ProductAppearance`` doesn't persist ``peak_confidence``;
    the adapter approximates with ``avg_confidence``. Used only by
    the picker's overshoot trim, not the scorer's composite score,
    so the approximation is harmless."""
    appearance = _make_appearance(avg_confidence=0.74)
    aw = _appearance_to_annotated_window(appearance)
    assert aw.peak_confidence == pytest.approx(0.74)


def test_adapter_synthesizes_frame_count_at_5fps_cadence() -> None:
    """SAM2 samples at 5fps (200ms cadence). ``frame_count`` is
    estimated from window duration / 200ms — only used by the
    scorer when ``avg_bbox_area_pct`` is the dominant signal, which
    it is for v1."""
    appearance = _make_appearance(
        window_start_ms=0, window_end_ms=2_000,  # 2s window
    )
    aw = _appearance_to_annotated_window(appearance)
    assert aw.frame_count == 10  # 2_000ms / 200ms = 10 frames


def test_adapter_clamps_frame_count_at_one() -> None:
    """Sub-200ms windows would produce frame_count=0 via integer
    division. Clamp at 1 so the dataclass doesn't carry zero
    frames (which would crash downstream avg-related math)."""
    appearance = _make_appearance(
        window_start_ms=0, window_end_ms=100,  # 100ms — sub-cadence
    )
    aw = _appearance_to_annotated_window(appearance)
    assert aw.frame_count == 1


def test_adapter_passes_through_rejected_reason() -> None:
    """Rejected appearances stay in the DB for tuning. The adapter
    passes the reason through so the scorer's :func:`score_windows`
    filter (``w.is_accepted``) sees the correct flag."""
    appearance = _make_appearance(rejected_reason="too_short")
    aw = _appearance_to_annotated_window(appearance)
    assert aw.rejected_reason == "too_short"


def test_adapter_drops_catalog_id_on_purpose() -> None:
    """The vendored ``AnnotatedWindow`` is catalog-blind by design
    (see ``children/picker.py``). Verify the adapter doesn't sneak
    a catalog_entry_id into the lib type — if it did, the vendor
    boundary would be subtly violated."""
    appearance = _make_appearance()
    aw = _appearance_to_annotated_window(appearance)
    # Inspect every public attr — none should be a UUID-shaped value
    # matching the appearance's catalog_entry_id.
    fields = [
        getattr(aw, name)
        for name in dir(aw)
        if not name.startswith("_") and not callable(getattr(aw, name))
    ]
    assert appearance.catalog_entry_id not in fields
