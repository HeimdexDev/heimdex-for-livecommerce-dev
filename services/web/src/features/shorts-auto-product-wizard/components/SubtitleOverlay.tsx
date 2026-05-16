"use client";

// ============================================================================
// SubtitleOverlay — WYSIWYG DOM caption layer for the auto-shorts product
// wizard's overlay-mode flow.
//
// Plan: .claude/plans/wysiwyg-subtitle-overlay-2026-05-11.md (Phase 2)
// Earlier plan: .claude/plans/auto-shorts-overlay-mode-2026-05-07.md
//
// Renders the cue active at `currentTimeMs` as a styled overlay element
// matching what the FFmpeg drawtext burn will produce. Per-cue style on
// the cue (Partial<SubtitleCueStyle>) flows through `resolveOverlayStyle`
// — when absent, the resolver falls back to the auto-shorts defaults so
// behavior is identical to the pre-WYSIWYG overlay.
//
// The component is intentionally feature-agnostic — it knows nothing
// about render jobs / refinement / chains. Inputs are just (cues,
// currentTimeMs, video/canvas dims); output is a positioned,
// pointer-events-none pill. Lift state at the page layer.
// ============================================================================

import { useMemo, type CSSProperties } from "react";

import {
  DEFAULT_CANVAS_HEIGHT,
  DEFAULT_CANVAS_WIDTH,
  resolveOverlayStyle,
  type SubtitleCueStyle,
  wrapKoreanSubtitleLines,
} from "@/lib/subtitle-layout";

export interface SubtitleOverlayCue {
  text: string;
  start_ms: number;
  end_ms: number;
  /**
   * Per-cue style override (subset of contracts ``SubtitleStyleSpec``).
   * When absent, the overlay falls back to the centralized auto-shorts
   * default — preserves backward compatibility for callers (e.g. Whisper
   * post-render cues) that don't carry style.
   */
  style?: Partial<SubtitleCueStyle>;
}

export interface SubtitleOverlayProps {
  /** Cues to display, in input_spec order. */
  cues: SubtitleOverlayCue[];
  /** Current playback time in ms (drives which cue is visible). */
  currentTimeMs: number;
  /**
   * Rendered video element dimensions (clientWidth / clientHeight). Falls
   * back to default canvas dims when the video hasn't laid out yet.
   */
  videoWidth: number | null;
  videoHeight: number | null;
  /**
   * Composition canvas dimensions — `CompositionSpec.output.width/height`.
   * Used to scale canvas-pixel style fields (font_size_px, padding,
   * stroke_width, shadow_offset_*) into rendered pixels. When omitted,
   * the resolver treats the rendered video AS the canvas (scale=1),
   * preserving today's behavior for callers that haven't been updated
   * to pass canvas dims yet.
   */
  canvasWidth?: number | null;
  canvasHeight?: number | null;
}

/**
 * Find the cue active at `currentTimeMs`, if any.
 *
 * Linear scan — N is small (≤ ~20 cues per clip) and the comparison is
 * trivial. A binary search would be premature.
 */
function findActiveCue(
  cues: SubtitleOverlayCue[],
  currentTimeMs: number,
): SubtitleOverlayCue | null {
  for (const cue of cues) {
    if (currentTimeMs >= cue.start_ms && currentTimeMs < cue.end_ms) {
      return cue;
    }
  }
  return null;
}

/**
 * Map text_align to a CSS transform that anchors the pill's edge
 * (left/center/right) to ``positionX``. Mirrors drawtext's
 * `_position_to_ffmpeg_x` semantics:
 *   - center → text centered at w*position_x (translate -50%)
 *   - right  → text ending at w*position_x (translate -100%)
 *   - left   → text starting at w*position_x (translate 0)
 *
 * Vertical: always -50% so the pill's vertical center sits at
 * ``positionY * H`` — matches drawtext's `h*position_y - block_height/2`
 * anchoring.
 */
function transformForAlign(textAlign: "left" | "center" | "right"): string {
  switch (textAlign) {
    case "left":
      return "translate(0, -50%)";
    case "right":
      return "translate(-100%, -50%)";
    case "center":
    default:
      return "translate(-50%, -50%)";
  }
}

export function SubtitleOverlay({
  cues,
  currentTimeMs,
  videoWidth,
  videoHeight,
  canvasWidth,
  canvasHeight,
}: SubtitleOverlayProps) {
  const renderedHeight =
    videoHeight && videoHeight > 0 ? videoHeight : DEFAULT_CANVAS_HEIGHT;
  const renderedWidth =
    videoWidth && videoWidth > 0 ? videoWidth : DEFAULT_CANVAS_WIDTH;

  const activeCue = useMemo(
    () => findActiveCue(cues, currentTimeMs),
    [cues, currentTimeMs],
  );

  // Resolve the per-cue style into CSS-ready values. When no cue is
  // active OR when the cue has no style, the resolver falls back to
  // auto-shorts defaults. Memoised on style + dims so the overlay
  // doesn't rebuild the CSS string on every <video> timeUpdate that
  // doesn't change the active cue.
  const resolved = useMemo(
    () =>
      resolveOverlayStyle({
        cueStyle: activeCue?.style ?? null,
        canvasWidth: canvasWidth ?? null,
        canvasHeight: canvasHeight ?? null,
        renderedWidth,
        renderedHeight,
      }),
    [
      activeCue?.style,
      canvasWidth,
      canvasHeight,
      renderedWidth,
      renderedHeight,
    ],
  );

  if (activeCue == null) return null;

  // Whisper post-render writes already-wrapped text (with `\n`) into
  // input_spec.subtitles. Manual edits via PATCH typically don't include
  // line breaks. Re-wrap defensively so the overlay's line breaks always
  // match what FFmpeg will draw — the python wrap is idempotent on
  // already-wrapped input shorter than the budget.
  const rawLines = activeCue.text.split("\n");
  const wrapped = rawLines
    .map((line) => wrapKoreanSubtitleLines(line, resolved.charsPerLine))
    .join("\n");
  const lines = wrapped.split("\n");

  // Padding asymmetry (vertical ~60% of horizontal) and border radius
  // (~50% of horizontal) preserve the visual proportions of the pre-
  // WYSIWYG pill. Operator style edits scale both via resolved.paddingPx.
  const verticalPad = Math.round(resolved.paddingPx * 0.6);
  const borderRadius = Math.round(resolved.paddingPx * 0.5);

  // When the cue explicitly disables the background (background=null),
  // drop padding + border-radius so the text floats clean rather than
  // sitting inside an invisible padded box.
  const hasBackground = resolved.background != null;

  const pillStyle: CSSProperties = {
    top: `${resolved.positionY * 100}%`,
    left: `${resolved.positionX * 100}%`,
    transform: transformForAlign(resolved.textAlign),
    backgroundColor: resolved.background ?? "transparent",
    color: resolved.fontColor,
    fontWeight: resolved.fontWeight,
    fontSize: resolved.fontSizePx,
    lineHeight: resolved.lineHeight,
    padding: hasBackground
      ? `${verticalPad}px ${resolved.paddingPx}px`
      : 0,
    borderRadius: hasBackground ? borderRadius : 0,
    textAlign: resolved.textAlign,
    whiteSpace: "pre",
    fontFamily: resolved.fontFamily,
    ...(resolved.webkitTextStroke
      ? {
          // CSS property name in the inline style attribute will be
          // `-webkit-text-stroke`. The camelCase form is the React
          // style-object key.
          WebkitTextStroke: resolved.webkitTextStroke,
        }
      : {}),
    ...(resolved.textShadow
      ? { textShadow: resolved.textShadow }
      : {}),
  };

  return (
    <div
      data-testid="subtitle-overlay"
      className="pointer-events-none absolute inset-0"
    >
      <div
        data-testid="subtitle-overlay-pill"
        className="absolute"
        style={pillStyle}
      >
        {lines.map((line, i) => (
          <span key={i} style={{ display: "block" }}>
            {line}
          </span>
        ))}
      </div>
    </div>
  );
}
