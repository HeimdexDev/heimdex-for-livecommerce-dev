"use client";

// ============================================================================
// SubtitleOverlay — WYSIWYG DOM caption layer for the auto-shorts product
// wizard's overlay-mode flow.
//
// Plan: .claude/plans/auto-shorts-overlay-mode-2026-05-07.md
//
// Renders the cue active at `currentTimeMs` as a white-pill black-bold-text
// element styled to match the FFmpeg drawtext burn that the export render
// will produce. The python source of truth for the styling is
// `subtitle_layout.py`; the TS mirror in `@/lib/subtitle-layout` carries
// the same constants. A snapshot test guards against drift.
//
// The component is intentionally feature-agnostic — it knows nothing about
// render jobs / refinement / chains. Inputs are just (cues, currentTimeMs,
// videoWidth, videoHeight); output is a positioned, pointer-events-none
// pill. Lift state at the page layer.
// ============================================================================

import { useMemo } from "react";

import {
  buildAutoShortsSubtitleStyle,
  computeCharsPerLine,
  DEFAULT_CANVAS_HEIGHT,
  DEFAULT_CANVAS_WIDTH,
  POSITION_Y,
  wrapKoreanSubtitleLines,
} from "@/lib/subtitle-layout";

export interface SubtitleOverlayCue {
  text: string;
  start_ms: number;
  end_ms: number;
}

export interface SubtitleOverlayProps {
  /** Cues to display, in input_spec order. */
  cues: SubtitleOverlayCue[];
  /** Current playback time in ms (drives which cue is visible). */
  currentTimeMs: number;
  /**
   * Rendered video element dimensions (clientWidth / clientHeight). The
   * overlay sizes the pill proportional to the video's actual on-screen
   * height — same `FONT_SIZE_RATIO_HEIGHT * canvasHeight` math the python
   * style uses, applied to the displayed height instead of the encoded
   * canvas height. Falls back to default canvas dims when the video hasn't
   * laid out yet (first paint).
   */
  videoWidth: number | null;
  videoHeight: number | null;
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

export function SubtitleOverlay({
  cues,
  currentTimeMs,
  videoWidth,
  videoHeight,
}: SubtitleOverlayProps) {
  const renderedHeight = videoHeight && videoHeight > 0 ? videoHeight : DEFAULT_CANVAS_HEIGHT;
  const renderedWidth = videoWidth && videoWidth > 0 ? videoWidth : DEFAULT_CANVAS_WIDTH;
  const style = useMemo(
    () => buildAutoShortsSubtitleStyle(renderedHeight),
    [renderedHeight],
  );

  const activeCue = useMemo(
    () => findActiveCue(cues, currentTimeMs),
    [cues, currentTimeMs],
  );

  if (activeCue == null) return null;

  const charsPerLine = computeCharsPerLine({
    canvasWidth: renderedWidth,
    fontSizePx: style.font_size_px,
    padding: style.background_padding,
  });

  // Whisper post-render writes already-wrapped text (with `\n`) into
  // input_spec.subtitles. Manual edits via PATCH typically don't include
  // line breaks. Re-wrap defensively so the overlay's line breaks always
  // match what FFmpeg will draw — the python wrap is idempotent on
  // already-wrapped input shorter than the budget.
  const rawLines = activeCue.text.split("\n");
  const wrapped = rawLines
    .map((line) => wrapKoreanSubtitleLines(line, charsPerLine))
    .join("\n");
  const lines = wrapped.split("\n");

  // `position_y=0.82` is the BASELINE (text origin) in FFmpeg drawtext
  // semantics — text grows upward from there. We anchor the pill's top
  // to the same fraction of the rendered video height; the pill grows
  // downward in DOM. Empirically this places the pill in the same visual
  // band as the burn at the canvas dims we care about (720p / 1080p).
  // For finer alignment we'd need the rendered text metrics, which
  // requires measurement; deferred until WYSIWYG QA shows drift.
  const topPx = Math.round(renderedHeight * POSITION_Y);
  const fontSizePx = style.font_size_px;
  const paddingPx = style.background_padding;
  const bgRgba = `rgba(255, 255, 255, ${style.background_opacity})`;

  return (
    <div
      data-testid="subtitle-overlay"
      className="pointer-events-none absolute left-0 right-0 flex justify-center"
      style={{
        top: topPx,
        // Translate the pill upward by half its (auto) height so the
        // visual center of the pill sits at `position_y`. Tailwind's
        // `-translate-y-1/2` would do this but we bypass it to avoid a
        // class-vs-inline-style conflict with `top`.
        transform: "translateY(-50%)",
      }}
    >
      <div
        data-testid="subtitle-overlay-pill"
        style={{
          backgroundColor: bgRgba,
          color: style.font_color,
          fontWeight: style.font_weight,
          fontSize: fontSizePx,
          lineHeight: 1.2,
          padding: `${Math.round(paddingPx * 0.6)}px ${paddingPx}px`,
          borderRadius: Math.round(paddingPx * 0.5),
          textAlign: "center",
          whiteSpace: "pre",
          // Pretendard is the project font (matches the worker's
          // bundled Pretendard variant — see
          // .claude/plans/pretendard-font-fix.md). System fallbacks
          // keep the overlay readable if the font fails to load.
          fontFamily: "Pretendard, system-ui, -apple-system, sans-serif",
          maxWidth: `calc(100% - ${paddingPx * 2}px)`,
        }}
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
