"""Tests for text template schemas."""

import pytest
from pydantic import ValidationError

from app.modules.text_templates.schemas import (
    TextTemplateCreate,
    TextTemplateResponse,
    TextTemplateUpdate,
)


class TestTextTemplateCreate:
    def test_defaults_applied(self) -> None:
        t = TextTemplateCreate(name="test")
        assert t.font_family == "Noto Sans KR"
        assert t.font_size_px == 48
        assert t.font_color == "#FFFFFF"
        assert t.font_weight == 700
        assert t.line_height == 1.4
        assert t.position_x == 0.5
        assert t.position_y == 0.85
        assert t.text_align == "center"
        assert t.shadow_enabled is True
        assert t.background_enabled is False

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TextTemplateCreate(name="")

    def test_name_too_long_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TextTemplateCreate(name="x" * 101)

    def test_font_size_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            TextTemplateCreate(name="test", font_size_px=200)
        with pytest.raises(ValidationError):
            TextTemplateCreate(name="test", font_size_px=5)

    def test_font_weight_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            TextTemplateCreate(name="test", font_weight=1000)


class TestTextTemplateUpdate:
    def test_partial_update(self) -> None:
        u = TextTemplateUpdate(font_color="#FF0000")
        assert u.font_color == "#FF0000"
        assert u.name is None
        assert u.font_size_px is None

    def test_exclude_unset(self) -> None:
        u = TextTemplateUpdate(font_color="#FF0000")
        data = u.model_dump(exclude_unset=True)
        assert data == {"font_color": "#FF0000"}


class TestTextTemplateResponse:
    def test_from_attributes(self) -> None:
        from types import SimpleNamespace
        from datetime import datetime, timezone
        from uuid import uuid4

        obj = SimpleNamespace(
            id=uuid4(), org_id=uuid4(), user_id=uuid4(),
            name="test", font_family="Noto Sans KR", font_size_px=48,
            font_color="#FFFFFF", font_weight=700, line_height=1.4,
            letter_spacing=0, position_x=0.5, position_y=0.85,
            text_align="center", shadow_enabled=True, shadow_color="#000000",
            shadow_offset_x=2, shadow_offset_y=2, shadow_blur=4,
            background_enabled=False, background_color=None,
            background_padding=8, is_system_preset=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        resp = TextTemplateResponse.model_validate(obj)
        assert resp.name == "test"
        assert resp.is_system_preset is False
