"""Pure-function tests for refinement_service helpers.

The orchestration in ``_run_refinement`` has many side effects (DB,
S3, Whisper, SQS) and is exercised in
``test_refinement_service_runner.py``. This file isolates the four
pure helpers that make routing decisions:

* ``_check_guards``
* ``_build_prompt_from_spec``
* ``_extract_timeline_duration_ms``
* ``_build_refined_input_spec``
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.lib.subtitle_chunking import Subtitle
from app.modules.shorts_render.refinement_service import (
    _build_prompt_from_spec,
    _build_refined_input_spec,
    _check_guards,
    _extract_timeline_duration_ms,
)


def _parent(
    *,
    refinement_source=None,
    replaced_by=None,
    refined_from=None,
    output_s3_key="org/render/output.mp4",
    subtitles_in_spec=True,
):
    spec = {
        "scene_clips": [{"timeline_end_ms": 30_000}],
    }
    if subtitles_in_spec:
        spec["subtitles"] = [{"text": "안녕", "start_ms": 0, "end_ms": 1000}]
    return SimpleNamespace(
        refinement_source=refinement_source,
        replaced_by_render_job_id=replaced_by,
        refined_from_render_job_id=refined_from,
        output_s3_key=output_s3_key,
        input_spec=spec,
    )


class TestCheckGuards:
    def test_clean_parent_proceeds(self) -> None:
        assert _check_guards(_parent()) is None

    def test_manual_edit_blocks(self) -> None:
        assert _check_guards(_parent(refinement_source="manual_edit")) == "manual_edit"

    def test_already_refined_blocks(self) -> None:
        assert _check_guards(_parent(replaced_by=uuid4())) == "already_refined"

    def test_refined_from_child_blocks(self) -> None:
        # This row IS a refined child — don't recurse
        assert _check_guards(_parent(refined_from=uuid4())) == "refined_from"

    def test_no_output_s3_key_blocks(self) -> None:
        assert _check_guards(_parent(output_s3_key=None)) == "no_output_s3_key"
        assert _check_guards(_parent(output_s3_key="")) == "no_output_s3_key"

    def test_no_subtitles_in_parent_blocks(self) -> None:
        assert _check_guards(_parent(subtitles_in_spec=False)) == "no_subtitles"

    def test_priority_manual_edit_over_already_refined(self) -> None:
        # Both flags set — manual_edit checked first
        p = _parent(refinement_source="manual_edit", replaced_by=uuid4())
        assert _check_guards(p) == "manual_edit"


class TestBuildPromptFromSpec:
    def test_returns_title_when_present(self) -> None:
        spec = {"title": "다이슨 헤어드라이어 후기"}
        assert _build_prompt_from_spec(spec) == "다이슨 헤어드라이어 후기"

    def test_strips_whitespace(self) -> None:
        spec = {"title": "  product name  "}
        assert _build_prompt_from_spec(spec) == "product name"

    def test_caps_at_600_chars(self) -> None:
        spec = {"title": "x" * 1000}
        assert len(_build_prompt_from_spec(spec)) == 600

    def test_returns_none_when_no_title(self) -> None:
        assert _build_prompt_from_spec({}) is None

    def test_returns_none_for_empty_title(self) -> None:
        assert _build_prompt_from_spec({"title": ""}) is None
        assert _build_prompt_from_spec({"title": "   "}) is None

    def test_returns_none_for_non_string_title(self) -> None:
        assert _build_prompt_from_spec({"title": 123}) is None
        assert _build_prompt_from_spec({"title": None}) is None
        assert _build_prompt_from_spec({"title": []}) is None


class TestExtractTimelineDurationMs:
    def test_max_of_clip_ends(self) -> None:
        spec = {
            "scene_clips": [
                {"timeline_end_ms": 5_000},
                {"timeline_end_ms": 30_000},
                {"timeline_end_ms": 15_000},
            ]
        }
        assert _extract_timeline_duration_ms(spec) == 30_000

    def test_no_clips_returns_none(self) -> None:
        assert _extract_timeline_duration_ms({}) is None
        assert _extract_timeline_duration_ms({"scene_clips": []}) is None

    def test_zero_end_returns_none(self) -> None:
        # max() of [0] is 0 → falsy → None per the implementation
        assert _extract_timeline_duration_ms(
            {"scene_clips": [{"timeline_end_ms": 0}]}
        ) is None

    def test_malformed_returns_none(self) -> None:
        assert _extract_timeline_duration_ms(
            {"scene_clips": [{"timeline_end_ms": "not-a-number"}]}
        ) is None


class TestBuildRefinedInputSpec:
    def test_swaps_only_subtitles_field(self) -> None:
        parent_spec = {
            "scene_clips": [{"video_id": "v1", "timeline_end_ms": 5000}],
            "subtitles": [
                {"text": "old", "start_ms": 0, "end_ms": 1000}
            ],
            "title": "my product",
            "version": 2,
            "output": {"width": 1080, "height": 1920},
        }
        new_subs = [
            Subtitle(start_ms=100, end_ms=900, text="new1"),
            Subtitle(start_ms=1000, end_ms=2000, text="new2"),
        ]
        result = _build_refined_input_spec(parent_spec, new_subs)
        assert result["scene_clips"] == parent_spec["scene_clips"]
        assert result["title"] == "my product"
        assert result["version"] == 2
        assert result["output"] == parent_spec["output"]
        assert len(result["subtitles"]) == 2
        assert result["subtitles"][0]["text"] == "new1"
        assert result["subtitles"][1]["start_ms"] == 1000

    def test_inherits_style_from_first_parent_subtitle(self) -> None:
        parent_spec = {
            "subtitles": [
                {
                    "text": "old",
                    "start_ms": 0,
                    "end_ms": 1000,
                    "style": {
                        "font_size": 48,
                        "background_color": "#000000",
                    },
                }
            ]
        }
        new_subs = [Subtitle(start_ms=0, end_ms=500, text="x")]
        result = _build_refined_input_spec(parent_spec, new_subs)
        assert result["subtitles"][0]["style"]["font_size"] == 48
        assert result["subtitles"][0]["style"]["background_color"] == "#000000"

    def test_inherits_template_id_from_first_parent_subtitle(self) -> None:
        parent_spec = {
            "subtitles": [
                {
                    "text": "old",
                    "start_ms": 0,
                    "end_ms": 1000,
                    "template_id": "auto_shorts_pill",
                }
            ]
        }
        new_subs = [Subtitle(start_ms=0, end_ms=500, text="x")]
        result = _build_refined_input_spec(parent_spec, new_subs)
        assert result["subtitles"][0]["template_id"] == "auto_shorts_pill"

    def test_drops_zero_or_negative_duration_chunks(self) -> None:
        # SubtitleSpec rejects end <= start; we filter pre-emptively
        new_subs = [
            Subtitle(start_ms=0, end_ms=500, text="ok"),
            Subtitle(start_ms=1000, end_ms=1000, text="zero_dur"),
        ]
        parent_spec = {
            "subtitles": [{"text": "x", "start_ms": 0, "end_ms": 100}]
        }
        result = _build_refined_input_spec(parent_spec, new_subs)
        assert len(result["subtitles"]) == 1
        assert result["subtitles"][0]["text"] == "ok"

    def test_no_parent_subtitles_yields_default_style(self) -> None:
        parent_spec = {"scene_clips": [{"timeline_end_ms": 5000}]}
        new_subs = [Subtitle(start_ms=0, end_ms=500, text="x")]
        result = _build_refined_input_spec(parent_spec, new_subs)
        # No style/template_id keys leaked from absent parent
        sub = result["subtitles"][0]
        assert "style" not in sub
        assert "template_id" not in sub
        assert sub == {"text": "x", "start_ms": 0, "end_ms": 500}

    def test_style_dict_is_copied_not_shared(self) -> None:
        """Mutating refined output's style must not affect parent."""
        parent_spec = {
            "subtitles": [
                {"text": "x", "start_ms": 0, "end_ms": 100, "style": {"k": 1}}
            ]
        }
        new_subs = [Subtitle(start_ms=0, end_ms=500, text="y")]
        result = _build_refined_input_spec(parent_spec, new_subs)
        result["subtitles"][0]["style"]["k"] = 999
        assert parent_spec["subtitles"][0]["style"]["k"] == 1

    def test_empty_new_subs_yields_empty_subtitles_list(self) -> None:
        parent_spec = {
            "subtitles": [{"text": "x", "start_ms": 0, "end_ms": 100}]
        }
        # Note: the orchestration normally rejects empty new_subs before
        # reaching this builder, but the function itself must not crash.
        result = _build_refined_input_spec(parent_spec, [])
        assert result["subtitles"] == []


class TestRoundTrip:
    """Sanity: refined dict can be re-validated by SubtitleSpec."""

    def test_refined_dict_validates_as_subtitle_spec(self) -> None:
        from heimdex_media_contracts.composition import SubtitleSpec

        new_subs = [
            Subtitle(start_ms=100, end_ms=900, text="안녕하세요"),
            Subtitle(start_ms=1000, end_ms=2000, text="여러분"),
        ]
        parent_spec = {
            "subtitles": [
                {"text": "old", "start_ms": 0, "end_ms": 100, "style": {}}
            ]
        }
        result = _build_refined_input_spec(parent_spec, new_subs)
        # Each refined sub must round-trip through the contract
        for raw in result["subtitles"]:
            spec = SubtitleSpec(**raw)
            assert spec.duration_ms > 0

    def test_refined_dict_rejects_bad_values(self) -> None:
        """Negative durations would never reach this point but we
        confirm the contract is the backstop."""
        from pydantic import ValidationError
        from heimdex_media_contracts.composition import SubtitleSpec

        with pytest.raises(ValidationError):
            SubtitleSpec(text="x", start_ms=100, end_ms=100)
