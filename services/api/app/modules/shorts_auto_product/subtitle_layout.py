"""Shared subtitle layout primitives for the auto-shorts product
flow.

Pure module — no I/O, no DB, no async. Holds the canvas-aware
styling and Korean-aware line-wrap helpers that BOTH the pre-render
composition_builder AND the post-render Whisper refinement need to
agree on. Lives outside ``track_stt/`` because both consumers sit at
different layers of the pipeline.

Public API:
    * ``build_auto_shorts_subtitle_style(canvas_height)``
    * ``compute_chars_per_line(canvas_width, font_size_px, padding)``
    * ``wrap_korean_subtitle_lines(text, chars_per_line)``
    * ``DEFAULT_CANVAS_WIDTH`` / ``DEFAULT_CANVAS_HEIGHT``
    * ``MAX_SUBTITLE_LINES``

Why centralised: when auto-shorts decoupled captions from OS
``speaker_transcript`` (2026-05-07), the refinement_service became
the sole caption source. It needed the same pill-style + line-wrap
budget that composition_builder previously owned. Forking the
constants into both modules would drift; sharing keeps them one
edit away from any future style change.
"""

from __future__ import annotations

from heimdex_media_contracts.composition.schemas import SubtitleStyleSpec


# Default canvas dimensions — match heimdex_media_contracts'
# ``OutputSpec`` defaults (406 × 720, 9:16 portrait at 720p height).
# Bumping these requires updating both this constant AND the
# ``OutputSpec`` carried in any composition that uses non-default
# dimensions.
DEFAULT_CANVAS_WIDTH = 406
DEFAULT_CANVAS_HEIGHT = 720

# Subtitle font size as a fraction of canvas height. 4.5% gives 32px
# at 720p, 49px at 1080p — readable on mobile, leaves ~12 Hangul
# chars of horizontal headroom per line at 9:16 portrait so the
# 어절-aware wrapper can fit most chunker-bounded cues without
# overflow. Pre-2026-05-06 hardcoded 36px overflowed at 720p (see
# staging incident: "근데 이번에 수량 좀 짜게" at 14 chars produced
# a ~450px pill on a 406-wide canvas).
_FONT_SIZE_RATIO_HEIGHT = 0.045

# Floor — never render below 16px (drawtext minimum legibility).
_FONT_SIZE_FLOOR_PX = 16

# Padding scales with font size (~33%) so the pill stays balanced
# at every canvas resolution.
_PADDING_RATIO_FONT = 0.33
_PADDING_FLOOR_PX = 8

# Max lines per cue when auto-wrapping. The upstream chunker
# (MAX_SUBTITLE_CHARS=25) keeps almost every cue inside 2 lines at
# the typical 11-13 chars/line budget — going beyond crowds the
# 9:16 frame and competes with the product staging.
MAX_SUBTITLE_LINES = 2

# Safety multiplier on the per-line pixel budget. Naive
# ``available_width / font_size_px`` math sits the pill flush
# against the frame edge for dense Hangul cues — any rendering
# variance (Pretendard glyph width is 0.85-0.95em, not exact 1em)
# would push past the frame. 0.92 backs the budget off ~8% so the
# rendered pill stays comfortably inside the frame.
_LINE_BUDGET_SAFETY = 0.92


def build_auto_shorts_subtitle_style(
    *, canvas_height: int = DEFAULT_CANVAS_HEIGHT,
) -> SubtitleStyleSpec:
    """Build the auto-shorts subtitle style sized to the canvas.

    Pure function. ``font_size_px`` and ``background_padding`` scale
    with ``canvas_height``; everything else (colors, weight,
    position_y) is fixed because those are design choices, not
    resolution-dependent values.

    White pill on black-text — matches the operator-target
    screenshot and stays legible against any livecommerce
    background (white studio walls 흰 스튜디오 vs busy product
    layouts).
    """
    font_size_px = max(
        _FONT_SIZE_FLOOR_PX,
        round(canvas_height * _FONT_SIZE_RATIO_HEIGHT),
    )
    padding = max(
        _PADDING_FLOOR_PX,
        round(font_size_px * _PADDING_RATIO_FONT),
    )
    return SubtitleStyleSpec(
        font_color="#000000",
        background_color="#FFFFFF",
        background_opacity=0.95,
        background_padding=padding,
        font_weight=700,
        font_size_px=font_size_px,
        # Position bottom-center, slightly above the very bottom so
        # it doesn't fight with iOS / Android safe-area UI bars when
        # the short is reposted to social.
        position_y=0.82,
    )


def compute_chars_per_line(
    *,
    canvas_width: int,
    font_size_px: int,
    padding: int,
) -> int:
    """Estimate the maximum Hangul-density chars that fit one line.

    Hangul syllables in Pretendard Bold are ~0.9em wide; spaces and
    Latin chars are narrower. Using ``font_size_px`` as the per-char
    estimate already gives a conservative lower bound — applying
    ``_LINE_BUDGET_SAFETY`` (0.92) on top reserves a small visible
    gap on each side of the rendered pill so the border and shadow
    have room without abutting the frame edge.
    """
    available_px = max(0, canvas_width - 2 * padding)
    if font_size_px <= 0:
        return 0
    return int(available_px * _LINE_BUDGET_SAFETY) // font_size_px


def wrap_korean_subtitle_lines(
    text: str,
    *,
    chars_per_line: int,
    max_lines: int = MAX_SUBTITLE_LINES,
) -> str:
    """Greedy 어절-aware wrap returning text with ``\\n`` at breaks.

    Korean 어절 (words) are whitespace-separated; greedy left-to-right
    fills each line with as many 어절 as fit within
    ``chars_per_line``. If a single 어절 exceeds the budget,
    mid-syllable break — rare in practice (Korean words are
    typically ≤ 4 syllables).

    The renderer's drawtext filter interprets ``\\n`` as a line
    break and grows the background pill to enclose all lines.

    Caps at ``max_lines`` — text overflowing the cap is appended to
    the last line (defensive: better to slightly overflow than to
    truncate the operator's words).
    """
    text = text.strip()
    if chars_per_line <= 0 or len(text) <= chars_per_line:
        return text

    lines: list[str] = []
    remaining = text
    while remaining and len(lines) < max_lines:
        if len(remaining) <= chars_per_line:
            lines.append(remaining)
            remaining = ""
            break
        window = remaining[: chars_per_line + 1]
        last_space = window.rfind(" ")
        if last_space > 0:
            lines.append(remaining[:last_space])
            remaining = remaining[last_space + 1 :].lstrip()
        else:
            lines.append(remaining[:chars_per_line])
            remaining = remaining[chars_per_line:]

    if remaining:
        if lines:
            lines[-1] = (lines[-1] + " " + remaining).strip()
        else:
            lines.append(remaining)

    return "\n".join(lines)
