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
// ============================================================================
// Per-cue style resolver — used by <SubtitleOverlay> to honor
// operator-set SubtitleStyleSpec values while preserving the default
// auto-shorts pill when no per-cue style is present.
//
// Plan: .claude/plans/wysiwyg-subtitle-overlay-2026-05-11.md (Phase 1)
//
// SubtitleCueStyle mirrors `heimdex_media_contracts.composition.SubtitleStyleSpec`
// 1:1. Tolerant of partial input: every field is independently fallbacked
// onto `buildAutoShortsSubtitleStyle(canvasHeight)` + sane defaults.
//
// Canvas vs rendered:
//   - Style fields are CANVAS pixels (output.height, default 720).
//   - The <video> preview is rendered at CSS pixels.
//   - `scale = renderedHeight / canvasHeight` scales font_size_px,
//     background_padding, stroke_width, shadow_offset_*.
//   - When `canvasWidth/canvasHeight` are omitted, the resolver treats
//     the rendered video AS the canvas (scale=1). That preserves
//     today's <SubtitleOverlay> behavior for callers that haven't
//     plumbed canvas dims yet.
// ============================================================================

export interface SubtitleCueStyle {
  font_family: string;
  font_size_px: number;
  font_color: string;
  font_weight: number;
  text_align: "left" | "center" | "right";
  line_height: number;
  letter_spacing: number;
  position_x: number;
  position_y: number;
  background_color: string | null;
  background_padding: number;
  background_opacity: number;
  stroke_color: string | null;
  stroke_width: number;
  shadow_enabled: boolean;
  shadow_color: string | null;
  shadow_offset_x: number;
  shadow_offset_y: number;
}

export interface ResolvedOverlayStyle {
  /** Full CSS font-family stack, ready to drop into ``style``. */
  fontFamily: string;
  /** Rendered-pixel font size. */
  fontSizePx: number;
  fontWeight: number;
  fontColor: string;
  textAlign: "left" | "center" | "right";
  /** CSS line-height (unitless). */
  lineHeight: number;
  /** Horizontal padding in rendered pixels. Vertical padding is a
   * presentation choice in the overlay component (currently ~0.6× H). */
  paddingPx: number;
  /** ``rgba(...)`` string or null when no background should render. */
  background: string | null;
  /** ``-webkit-text-stroke`` value or null when no stroke should render. */
  webkitTextStroke: string | null;
  /** ``text-shadow`` value or null when no shadow should render. */
  textShadow: string | null;
  /** Normalized horizontal position [0, 1]. */
  positionX: number;
  /** Normalized vertical position [0, 1]. */
  positionY: number;
  /** Chars-per-line budget for ``wrapKoreanSubtitleLines`` — computed
   * from CANVAS dims so the wrap matches what FFmpeg drawtext would
   * wrap (if it wrapped — drawtext draws verbatim; the wrap is what
   * Whisper/operator-edits should target). */
  charsPerLine: number;
}

interface ResolveArgs {
  cueStyle: Partial<SubtitleCueStyle> | null | undefined;
  /** Composition canvas width (CompositionSpec.output.width). Defaults
   * to ``renderedWidth`` (legacy "treat rendered as canvas" behavior). */
  canvasWidth?: number | null;
  /** Composition canvas height (CompositionSpec.output.height). Defaults
   * to ``renderedHeight``. */
  canvasHeight?: number | null;
  /** Actual video element dimensions in CSS pixels. */
  renderedWidth: number;
  renderedHeight: number;
}

const DEFAULT_LINE_HEIGHT = 1.2;
const FALLBACK_FONT_FAMILY = "Pretendard";

export function resolveOverlayStyle(args: ResolveArgs): ResolvedOverlayStyle {
  const renderedW = Math.max(1, args.renderedWidth);
  const renderedH = Math.max(1, args.renderedHeight);
  const canvasW =
    args.canvasWidth && args.canvasWidth > 0 ? args.canvasWidth : renderedW;
  const canvasH =
    args.canvasHeight && args.canvasHeight > 0 ? args.canvasHeight : renderedH;
  const scale = renderedH / canvasH;

  const defaults = buildAutoShortsSubtitleStyle(canvasH);
  const cue = args.cueStyle ?? null;

  const canvasFontSize = cue?.font_size_px ?? defaults.font_size_px;
  const fontSizePx = Math.max(1, Math.round(canvasFontSize * scale));
  const fontWeight = cue?.font_weight ?? defaults.font_weight;
  const fontColor = cue?.font_color ?? defaults.font_color;
  const textAlign = cue?.text_align ?? "center";
  const lineHeight = cue?.line_height ?? DEFAULT_LINE_HEIGHT;
  const canvasPadding = cue?.background_padding ?? defaults.background_padding;
  const paddingPx = Math.max(0, Math.round(canvasPadding * scale));
  const positionX = cue?.position_x ?? 0.5;
  const positionY = cue?.position_y ?? defaults.position_y;

  // Background: explicit null (operator turned bg off) yields no
  // render. Missing field on a cue → fall back to the default pill.
  const bgColor =
    cue && "background_color" in cue
      ? cue.background_color
      : defaults.background_color;
  const bgOpacity = cue?.background_opacity ?? defaults.background_opacity;
  const background =
    bgColor != null ? hexToRgba(bgColor, bgOpacity) : null;

  // Stroke: rendered only when both color and a positive width are set.
  // Mirrors drawtext's `has_stroke` semantics.
  const strokeColor = cue?.stroke_color ?? null;
  const strokeWidthRendered = Math.max(
    0,
    Math.round((cue?.stroke_width ?? 0) * scale),
  );
  const webkitTextStroke =
    strokeColor && strokeWidthRendered > 0
      ? `${strokeWidthRendered}px ${strokeColor}`
      : null;

  // Shadow: rendered only when enabled AND a color is set. Mirrors
  // drawtext's `has_shadow` semantics. Blur is 0 (drawtext has no blur).
  const shadowEnabled = cue?.shadow_enabled ?? false;
  const shadowColor = cue?.shadow_color ?? null;
  const shadowDx = Math.round((cue?.shadow_offset_x ?? 0) * scale);
  const shadowDy = Math.round((cue?.shadow_offset_y ?? 0) * scale);
  const textShadow =
    shadowEnabled && shadowColor
      ? `${shadowDx}px ${shadowDy}px 0 ${shadowColor}`
      : null;

  const charsPerLine = computeCharsPerLine({
    canvasWidth: canvasW,
    fontSizePx: canvasFontSize,
    padding: canvasPadding,
  });

  return {
    fontFamily: formatFontFamily(cue?.font_family),
    fontSizePx,
    fontWeight,
    fontColor,
    textAlign,
    lineHeight,
    paddingPx,
    background,
    webkitTextStroke,
    textShadow,
    positionX,
    positionY,
    charsPerLine,
  };
}

function formatFontFamily(name: string | null | undefined): string {
  const family = name && name.length > 0 ? name : FALLBACK_FONT_FAMILY;
  return `"${family}", system-ui, -apple-system, sans-serif`;
}

/**
 * Parse a hex color (``#RRGGBB`` or ``#RRGGBBAA``; alpha ignored — callers
 * pass opacity separately) into an ``rgba(r, g, b, opacity)`` string.
 * Returns ``rgba(255, 255, 255, opacity)`` for malformed input so the
 * overlay always has something to render.
 */
function hexToRgba(hex: string, opacity: number): string {
  const match = /^#([0-9a-fA-F]{6})(?:[0-9a-fA-F]{2})?$/.exec(hex);
  if (!match) {
    return `rgba(255, 255, 255, ${opacity})`;
  }
  const r = parseInt(match[1].slice(0, 2), 16);
  const g = parseInt(match[1].slice(2, 4), 16);
  const b = parseInt(match[1].slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${opacity})`;
}

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
