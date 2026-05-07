"""Tests for ``storyboard.factory.build_storyboard_picker_from_settings``.

The factory is the seam between settings and the picker
implementations. Tests cover:

* Default-off behavior (returns None when flag absent or False).
* Heuristic picker construction with budgets sourced from settings.
* LLM picker raises NotImplementedError until Tier C lands.
* Unknown picker name raises ValueError loudly.
* Missing settings attributes default safely (real Settings has
  them, but tests + early-startup code paths may pass partial
  objects).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.modules.shorts_auto_product.track_stt.storyboard import (
    HeuristicStoryboardPicker,
    SlotBudgets,
    build_storyboard_picker_from_settings,
)


def _settings(**overrides):
    """Build a settings stub with explicit values for every flag the
    factory reads. Defaults match production config.py defaults so
    each test only needs to override the flags it cares about.
    """
    s = MagicMock()
    s.auto_shorts_product_v2_storyboard_mode_enabled = False
    s.auto_shorts_product_v2_storyboard_picker = "heuristic"
    s.auto_shorts_product_v2_storyboard_hook_ms = 8_000
    s.auto_shorts_product_v2_storyboard_intro_ms = 12_000
    s.auto_shorts_product_v2_storyboard_detail_ms = 25_000
    s.auto_shorts_product_v2_storyboard_cta_ms = 8_000
    for key, val in overrides.items():
        setattr(s, key, val)
    return s


class TestFactoryDisabled:
    def test_returns_none_when_flag_disabled(self) -> None:
        # Default config — storyboard mode off → no picker built.
        # Service.py uses None as the signal to fall back to the
        # legacy ``clip_selector`` path.
        assert build_storyboard_picker_from_settings(_settings()) is None

    def test_returns_none_when_flag_attribute_missing(self) -> None:
        # ``getattr(..., default=False)`` must default-disable when
        # an older settings object lacks the new attribute. Without
        # this, an in-flight deploy where the api hasn't picked up
        # config.py changes could spuriously enable storyboard mode.
        class BareSettings:
            pass

        assert build_storyboard_picker_from_settings(BareSettings()) is None


class TestFactoryHeuristic:
    def test_returns_heuristic_when_flag_enabled(self) -> None:
        picker = build_storyboard_picker_from_settings(
            _settings(auto_shorts_product_v2_storyboard_mode_enabled=True),
        )
        assert isinstance(picker, HeuristicStoryboardPicker)

    def test_budgets_sourced_from_settings(self) -> None:
        picker = build_storyboard_picker_from_settings(
            _settings(
                auto_shorts_product_v2_storyboard_mode_enabled=True,
                auto_shorts_product_v2_storyboard_hook_ms=4_000,
                auto_shorts_product_v2_storyboard_intro_ms=10_000,
                auto_shorts_product_v2_storyboard_detail_ms=30_000,
                auto_shorts_product_v2_storyboard_cta_ms=6_000,
            ),
        )
        assert isinstance(picker, HeuristicStoryboardPicker)
        assert picker.budgets == SlotBudgets(
            hook_ms=4_000, intro_ms=10_000, detail_ms=30_000, cta_ms=6_000,
        )


class TestFactoryLlm:
    def test_llm_picker_raises_until_tier_c(self) -> None:
        # Loud failure: operators flipping the picker to "llm" before
        # Tier C lands must SEE the misconfiguration. Silent fallback
        # to heuristic would mask the deployment error.
        with pytest.raises(NotImplementedError, match="Tier C"):
            build_storyboard_picker_from_settings(
                _settings(
                    auto_shorts_product_v2_storyboard_mode_enabled=True,
                    auto_shorts_product_v2_storyboard_picker="llm",
                ),
            )


class TestFactoryUnknownPicker:
    def test_unknown_picker_name_raises(self) -> None:
        # Defensive — if a typo lands in env config we want a clear
        # ValueError, not a silent picker miss.
        with pytest.raises(ValueError, match="unknown.*storyboard_picker"):
            build_storyboard_picker_from_settings(
                _settings(
                    auto_shorts_product_v2_storyboard_mode_enabled=True,
                    auto_shorts_product_v2_storyboard_picker="random",
                ),
            )
