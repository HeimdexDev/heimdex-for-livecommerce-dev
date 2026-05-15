"""Validator tests for shorts_auto request schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.shorts_auto.schemas import (
    AutoRenderRequest,
    AutoSelectRequest,
    ScoringModeRequest,
)


class TestAutoSelectRequest:
    def test_valid_both_mode(self):
        req = AutoSelectRequest(video_id="v1", mode=ScoringModeRequest.BOTH)
        assert req.count == 5
        assert req.target_duration_sec == 60
        assert req.min_duration_sec == 30
        assert req.prefer_continuous is True

    def test_human_mode_requires_person_cluster_id(self):
        with pytest.raises(ValidationError, match="person_cluster_id is required"):
            AutoSelectRequest(video_id="v1", mode=ScoringModeRequest.HUMAN)

    def test_human_mode_with_person_ok(self):
        req = AutoSelectRequest(
            video_id="v1",
            mode=ScoringModeRequest.HUMAN,
            person_cluster_id="p_abc123",
        )
        assert req.person_cluster_id == "p_abc123"

    def test_product_mode_does_not_require_person(self):
        req = AutoSelectRequest(video_id="v1", mode=ScoringModeRequest.PRODUCT)
        assert req.person_cluster_id is None

    def test_count_lower_bound(self):
        with pytest.raises(ValidationError):
            AutoSelectRequest(video_id="v1", mode=ScoringModeRequest.BOTH, count=0)

    def test_count_upper_bound(self):
        with pytest.raises(ValidationError):
            AutoSelectRequest(video_id="v1", mode=ScoringModeRequest.BOTH, count=11)

    def test_target_duration_lower_bound(self):
        with pytest.raises(ValidationError):
            AutoSelectRequest(
                video_id="v1", mode=ScoringModeRequest.BOTH, target_duration_sec=14
            )

    def test_min_must_not_exceed_target(self):
        with pytest.raises(ValidationError, match="min_duration_sec must be"):
            AutoSelectRequest(
                video_id="v1",
                mode=ScoringModeRequest.BOTH,
                target_duration_sec=30,
                min_duration_sec=45,
            )

    def test_video_id_non_empty(self):
        with pytest.raises(ValidationError):
            AutoSelectRequest(video_id="", mode=ScoringModeRequest.BOTH)


class TestAutoRenderRequest:
    def test_inherits_select_validators(self):
        with pytest.raises(ValidationError, match="person_cluster_id is required"):
            AutoRenderRequest(video_id="v1", mode=ScoringModeRequest.HUMAN)

    def test_default_auto_caption_off(self):
        req = AutoRenderRequest(video_id="v1", mode=ScoringModeRequest.BOTH)
        assert req.auto_caption is False

    def test_title_optional(self):
        req = AutoRenderRequest(video_id="v1", mode=ScoringModeRequest.BOTH, title="My short")
        assert req.title == "My short"

    def test_title_max_length(self):
        with pytest.raises(ValidationError):
            AutoRenderRequest(
                video_id="v1",
                mode=ScoringModeRequest.BOTH,
                title="x" * 256,
            )
