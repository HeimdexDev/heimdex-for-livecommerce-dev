"""Smoke test for the vendored ``app.lib.product_track`` chain.

Asserts the vendor decision (see
``app/lib/product_track/__init__.py``) holds:

  1. The pure-math chain imports cleanly inside the API venv.
  2. The upstream ``heimdex_media_pipelines`` package is NOT
     importable from the API — that is the whole reason for the
     vendor. If a future commit accidentally adds the upstream
     package as a dep, this test fails so the drift is caught
     before the API starts depending on a lib that isn't on PyPI.

Fast (<10ms): pure imports + a couple of constructions.
"""

from __future__ import annotations

from importlib import import_module

import pytest


def test_vendored_chain_imports_cleanly() -> None:
    """Every vendored submodule resolves without ImportError."""
    for mod_name in (
        "app.lib.product_track.config",
        "app.lib.product_track.window_assembly",
        "app.lib.product_track.alignment",
        "app.lib.product_track.subset_selector",
        "app.lib.product_track.stitching",
    ):
        # ``import_module`` raises ImportError if the chain is broken.
        import_module(mod_name)


def test_public_api_surface_present() -> None:
    """The runner imports these specific names — assert they exist."""
    from app.lib.product_track.config import (
        SUBSET_PICKER_VERSION,
        TRACKER_VERSION,
        TrackingConfig,
    )
    from app.lib.product_track.stitching import (
        StitchPlan,
        build_stitch_plan,
    )
    from app.lib.product_track.subset_selector import (
        GreedyPicker,
        ScoredWindow,
        SubsetPicker,
        score_windows,
        select_subset,
    )

    # Exercise the dataclasses just enough to confirm they aren't
    # empty stubs after a botched vendor sync.
    assert isinstance(TRACKER_VERSION, str) and TRACKER_VERSION
    assert isinstance(SUBSET_PICKER_VERSION, str) and SUBSET_PICKER_VERSION
    cfg = TrackingConfig()
    assert cfg.tracker_version == TRACKER_VERSION
    # GreedyPicker is the no-LLM fallback used in tests + the
    # ``OPENAI_API_KEY``-absent code paths.
    GreedyPicker()


def test_upstream_package_not_importable_from_api() -> None:
    """The whole point of vendoring: ``heimdex_media_pipelines`` must
    NOT be installed in the API venv. If this fails, somebody added
    the upstream package as a dep — either via ``pyproject.toml``
    or a path-mount — and the API has grown a build-time coupling
    to a repo that doesn't publish to PyPI.

    Resolution: either remove the upstream dep, or update the
    vendor docs (``app/lib/product_track/__init__.py``) to reflect
    the new install model and delete the vendored copy.
    """
    with pytest.raises(ImportError):
        import_module("heimdex_media_pipelines")
