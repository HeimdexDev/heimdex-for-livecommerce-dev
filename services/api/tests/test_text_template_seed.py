"""Tests for text template seed preset data and seeding logic."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


class TestSystemPresetData:
    """Test the preset definitions without importing the full seed module."""

    def _load_presets(self):
        """Import just the preset list."""
        # Import the constant directly — seed module top-level imports
        # may fail outside Docker, so we guard with a mock
        import importlib
        import sys

        # Mock heavy deps that seed.py imports at module level
        mocks = {}
        for mod in [
            "app.modules.search.client",
            "app.modules.search.scene_client",
            "app.modules.search.embedding",
            "app.modules.search",
            "app.modules.search.service",
            "opensearchpy",
            "tenacity",
        ]:
            if mod not in sys.modules:
                mocks[mod] = MagicMock()
                sys.modules[mod] = mocks[mod]

        try:
            if "app.seed" in sys.modules:
                importlib.reload(sys.modules["app.seed"])
            from app.seed import SYSTEM_TEXT_PRESETS
            return SYSTEM_TEXT_PRESETS
        finally:
            for mod in mocks:
                sys.modules.pop(mod, None)

    def test_5_presets_defined(self) -> None:
        presets = self._load_presets()
        assert len(presets) == 5

    def test_기본_values(self) -> None:
        presets = self._load_presets()
        p = presets[0]
        assert p["name"] == "기본"
        assert p["font_color"] == "#FFFFFF"
        assert p["font_size_px"] == 48
        assert p["position_y"] == 0.85
        assert p["text_align"] == "center"
        assert p["font_family"] == "Noto Sans KR"
        assert p["shadow_enabled"] is True

    def test_강조_values(self) -> None:
        presets = self._load_presets()
        p = presets[1]
        assert p["name"] == "강조"
        assert p["font_color"] == "#FFD700"
        assert p["font_size_px"] == 64
        assert p["position_y"] == 0.5
        assert p["font_family"] == "Pretendard"

    def test_제품소개_values(self) -> None:
        presets = self._load_presets()
        p = presets[2]
        assert p["name"] == "제품소개"
        assert p["font_size_px"] == 36
        assert p["font_weight"] == 400
        assert p["text_align"] == "left"
        assert p["position_x"] == 0.08
        assert p["position_y"] == 0.12
        assert p["background_enabled"] is True
        assert p["background_color"] == "#000000B3"
        assert p["background_padding"] == 12

    def test_가격_values(self) -> None:
        presets = self._load_presets()
        p = presets[3]
        assert p["name"] == "가격"
        assert p["font_color"] == "#FF4444"
        assert p["font_size_px"] == 56
        assert p["shadow_color"] == "#FFFFFF"
        assert p["font_family"] == "Pretendard"

    def test_엔딩_values(self) -> None:
        presets = self._load_presets()
        p = presets[4]
        assert p["name"] == "엔딩"
        assert p["font_size_px"] == 42
        assert p["shadow_blur"] == 8
        assert p["shadow_offset_x"] == 3
        assert p["shadow_offset_y"] == 3
        assert p["position_y"] == 0.5

    def test_all_presets_have_required_fields(self) -> None:
        presets = self._load_presets()
        required = {"name", "font_family", "font_size_px", "font_color", "font_weight",
                     "line_height", "letter_spacing", "text_align", "position_x", "position_y",
                     "shadow_enabled", "shadow_color", "shadow_offset_x", "shadow_offset_y",
                     "shadow_blur", "background_enabled", "background_color", "background_padding"}
        for p in presets:
            assert required.issubset(p.keys()), f"Missing fields in preset {p['name']}"
