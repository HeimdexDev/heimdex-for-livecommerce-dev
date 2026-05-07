// ============================================================================
// TypeScript mirror of services/api/app/modules/shorts_auto_product/subtitle_layout.py
//
// Plan: .claude/plans/auto-shorts-overlay-mode-2026-05-07.md
//
// The auto-shorts product wizard's overlay-mode caption flow renders cues
// in the browser via a DOM overlay so operators see WYSIWYG previews of the
// caption that the FFmpeg drawtext renderer will later burn in on export.
//
// Drift between this file and the python source produces a visible
// "edit-vs-final" mismatch for operators (different font size, different
// line wrap, different vertical placement). To prevent that, every constant
// here mirrors `subtitle_layout.py` 1:1, and `subtitle-layout.test.ts`
// asserts the values match a snapshot generated from the python source.
//
// Bump-in-lockstep workflow: when changing any constant, update BOTH this
// file AND `subtitle_layout.py` AND regenerate the snapshot. The snapshot
// test will fail loudly if you miss a side.
// ============================================================================

/** Default canvas dims — matches `OutputSpec` defaults (9:16 portrait, 720p). */
export const DEFAULT_CANVAS_WIDTH = 406;
export const DEFAULT_CANVAS_HEIGHT = 720;

/**
 * Subtitle font size as a fraction of canvas height. 4.5% gives 32px at 720p.
 * Korean Hangul fits ~12 chars/line at 9:16 with this size.
 */
export const FONT_SIZE_RATIO_HEIGHT = 0.045;

/** Absolute floor — never render below 16px. */
export const FONT_SIZE_FLOOR_PX = 16;

/** Padding scales with font size (~33%) so the pill stays balanced. */
export const PADDING_RATIO_FONT = 0.33;
export const PADDING_FLOOR_PX = 8;

/** Max wrap lines per cue. */
export const MAX_SUBTITLE_LINES = 2;

/**
 * Safety multiplier on per-line pixel budget (Pretendard glyph variance).
 * Backs off ~8% so dense Hangul cues stay inside the frame.
 */
export const LINE_BUDGET_SAFETY = 0.92;

/** Bottom-anchored Y position as a fraction of canvas height. */
export const POSITION_Y = 0.82;

/** Pill colors. */
export const FONT_COLOR = "#000000";
export const BACKGROUND_COLOR = "#FFFFFF";
export const BACKGROUND_OPACITY = 0.95;
export const FONT_WEIGHT = 700;

/** Resolved style payload (mirror of `SubtitleStyleSpec.model_dump()`). */
export interface SubtitleStyleSnapshot {
  font_color: string;
  background_color: string;
  background_opacity: number;
  background_padding: number;
  font_weight: number;
  font_size_px: number;
  position_y: number;
}

export function computeFontSizePx(canvasHeight: number): number {
  return Math.max(
    FONT_SIZE_FLOOR_PX,
    Math.round(canvasHeight * FONT_SIZE_RATIO_HEIGHT),
  );
}

export function computePaddingPx(fontSizePx: number): number {
  return Math.max(PADDING_FLOOR_PX, Math.round(fontSizePx * PADDING_RATIO_FONT));
}

export function buildAutoShortsSubtitleStyle(
  canvasHeight: number = DEFAULT_CANVAS_HEIGHT,
): SubtitleStyleSnapshot {
  const fontSizePx = computeFontSizePx(canvasHeight);
  return {
    font_color: FONT_COLOR,
    background_color: BACKGROUND_COLOR,
    background_opacity: BACKGROUND_OPACITY,
    background_padding: computePaddingPx(fontSizePx),
    font_weight: FONT_WEIGHT,
    font_size_px: fontSizePx,
    position_y: POSITION_Y,
  };
}

export function computeCharsPerLine(args: {
  canvasWidth: number;
  fontSizePx: number;
  padding: number;
}): number {
  const { canvasWidth, fontSizePx, padding } = args;
  const availablePx = Math.max(0, canvasWidth - 2 * padding);
  if (fontSizePx <= 0) return 0;
  return Math.floor((availablePx * LINE_BUDGET_SAFETY) / fontSizePx);
}

/**
 * Greedy 어절-aware Korean line wrap. Mirrors
 * `wrap_korean_subtitle_lines(text, chars_per_line)` in
 * subtitle_layout.py exactly.
 *
 * Returns the original text unchanged when `charsPerLine <= 0` or when the
 * input already fits on one line. Caps at `MAX_SUBTITLE_LINES`; overflow is
 * appended to the last line (defensive — never truncate operator words).
 */
export function wrapKoreanSubtitleLines(
  text: string,
  charsPerLine: number,
  maxLines: number = MAX_SUBTITLE_LINES,
): string {
  const trimmed = text.trim();
  if (charsPerLine <= 0 || trimmed.length <= charsPerLine) {
    return trimmed;
  }

  const lines: string[] = [];
  let remaining = trimmed;
  while (remaining.length > 0 && lines.length < maxLines) {
    if (remaining.length <= charsPerLine) {
      lines.push(remaining);
      remaining = "";
      break;
    }
    const window = remaining.slice(0, charsPerLine + 1);
    const lastSpace = window.lastIndexOf(" ");
    if (lastSpace > 0) {
      lines.push(remaining.slice(0, lastSpace));
      remaining = remaining.slice(lastSpace + 1).replace(/^\s+/, "");
    } else {
      lines.push(remaining.slice(0, charsPerLine));
      remaining = remaining.slice(charsPerLine);
    }
  }

  if (remaining.length > 0) {
    if (lines.length > 0) {
      lines[lines.length - 1] = `${lines[lines.length - 1]} ${remaining}`.trim();
    } else {
      lines.push(remaining);
    }
  }

  return lines.join("\n");
}
