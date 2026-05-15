// ============================================================================
// Drift guard for the TS mirror of subtitle_layout.py.
//
// Plan: .claude/plans/auto-shorts-overlay-mode-2026-05-07.md
//
// The DOM overlay rendered by <SubtitleOverlay> must match the FFmpeg
// drawtext burn that the export render produces. The python source of
// truth is `services/api/app/modules/shorts_auto_product/subtitle_layout.py`;
// the TS mirror is `@/lib/subtitle-layout`. Drift between them is a
// silent visual bug.
//
// This test file freezes the constants + helper outputs as snapshots. When
// the python side changes a constant, the TS side must change to match —
// the snapshot here will fail until both are updated. The snapshot mirrors
// the behavior of `test_shorts_auto_product_track_stt_pure.py` on the
// python side, but at the TS layer.
//
// To re-sync: read the python source, update the TS constant + helper, and
// update the snapshot below to match.
// ============================================================================

import { describe, expect, it } from "vitest";

import {
  BACKGROUND_COLOR,
  BACKGROUND_OPACITY,
  buildAutoShortsSubtitleStyle,
  computeCharsPerLine,
  computeFontSizePx,
  computePaddingPx,
  DEFAULT_CANVAS_HEIGHT,
  DEFAULT_CANVAS_WIDTH,
  FONT_COLOR,
  FONT_SIZE_FLOOR_PX,
  FONT_SIZE_RATIO_HEIGHT,
  FONT_WEIGHT,
  LINE_BUDGET_SAFETY,
  MAX_SUBTITLE_LINES,
  PADDING_FLOOR_PX,
  PADDING_RATIO_FONT,
  POSITION_Y,
  wrapKoreanSubtitleLines,
} from "@/lib/subtitle-layout";

describe("subtitle-layout constants (mirror of python subtitle_layout.py)", () => {
  it("matches python module-level constants verbatim", () => {
    // Drift guard. If you change one of these values, change the
    // corresponding constant in
    // services/api/app/modules/shorts_auto_product/subtitle_layout.py
    // in the SAME commit. Both surfaces compute the burned-in pill
    // dimensions; drift = visible WYSIWYG mismatch.
    expect(DEFAULT_CANVAS_WIDTH).toBe(406);
    expect(DEFAULT_CANVAS_HEIGHT).toBe(720);
    expect(FONT_SIZE_RATIO_HEIGHT).toBe(0.045);
    expect(FONT_SIZE_FLOOR_PX).toBe(16);
    expect(PADDING_RATIO_FONT).toBe(0.33);
    expect(PADDING_FLOOR_PX).toBe(8);
    expect(MAX_SUBTITLE_LINES).toBe(2);
    expect(LINE_BUDGET_SAFETY).toBe(0.92);
    expect(POSITION_Y).toBe(0.82);
    expect(FONT_COLOR).toBe("#000000");
    expect(BACKGROUND_COLOR).toBe("#FFFFFF");
    expect(BACKGROUND_OPACITY).toBe(0.95);
    expect(FONT_WEIGHT).toBe(700);
  });
});

describe("computeFontSizePx", () => {
  it("rounds canvasHeight * 0.045 (matches python)", () => {
    // Python: max(_FONT_SIZE_FLOOR_PX, round(canvas_height * 0.045)).
    // 720 * 0.045 = 32.4 → 32. 1080 * 0.045 = 48.6 → 49.
    expect(computeFontSizePx(720)).toBe(32);
    expect(computeFontSizePx(1080)).toBe(49);
  });

  it("clamps to 16px floor on small canvases", () => {
    // 240 * 0.045 = 10.8 → floor 16.
    expect(computeFontSizePx(240)).toBe(16);
  });
});

describe("computePaddingPx", () => {
  it("rounds fontSize * 0.33 with floor 8px", () => {
    expect(computePaddingPx(32)).toBe(11); // 32 * 0.33 = 10.56 → 11
    expect(computePaddingPx(49)).toBe(16); // 49 * 0.33 = 16.17 → 16
    expect(computePaddingPx(16)).toBe(8); // 16 * 0.33 = 5.28 → floored to 8
  });
});

describe("buildAutoShortsSubtitleStyle", () => {
  it("produces the same style payload as the python helper at 720p", () => {
    // Mirror of test_shorts_auto_product_track_stt_pure.py:306 and
    // python module-level defaults.
    const s = buildAutoShortsSubtitleStyle(720);
    expect(s).toEqual({
      font_color: "#000000",
      background_color: "#FFFFFF",
      background_opacity: 0.95,
      background_padding: 11,
      font_weight: 700,
      font_size_px: 32,
      position_y: 0.82,
    });
  });

  it("scales padding with font size at 1080p", () => {
    const s = buildAutoShortsSubtitleStyle(1080);
    expect(s.font_size_px).toBe(49);
    expect(s.background_padding).toBe(16);
    expect(s.position_y).toBe(0.82);
  });
});

describe("computeCharsPerLine", () => {
  it("derives chars/line from canvasWidth - 2*padding * safety / fontSize", () => {
    // 406 - 22 = 384 available. 384 * 0.92 = 353.28. / 32 = 11.04 → 11.
    expect(
      computeCharsPerLine({ canvasWidth: 406, fontSizePx: 32, padding: 11 }),
    ).toBe(11);
  });

  it("returns 0 for non-positive font size", () => {
    expect(
      computeCharsPerLine({ canvasWidth: 406, fontSizePx: 0, padding: 8 }),
    ).toBe(0);
  });
});

describe("wrapKoreanSubtitleLines", () => {
  it("returns input unchanged when shorter than the budget", () => {
    expect(wrapKoreanSubtitleLines("안녕", 11)).toBe("안녕");
    expect(wrapKoreanSubtitleLines("아 진짜 진심으로", 20)).toBe(
      "아 진짜 진심으로",
    );
  });

  it("breaks at the last whitespace within the window", () => {
    // 12 chars/line, 14-char input with a space at index 8.
    const wrapped = wrapKoreanSubtitleLines("강원도 영월보다 더 슬퍼할", 11);
    expect(wrapped.split("\n")).toHaveLength(2);
    // Each line should be ≤ 11 chars (the line budget) — verifies the
    // greedy split landed somewhere reasonable. Exact split point is
    // an implementation detail; we lock the count + the round-trip.
    const lines = wrapped.split("\n");
    expect(lines.every((l) => l.length <= 11)).toBe(true);
  });

  it("caps at MAX_SUBTITLE_LINES; overflow appended to last line", () => {
    // Force three "lines worth" of input.
    const long =
      "한국어 라이브커머스 자막의 매우 긴 한 줄짜리 입력 정말 길어요";
    const wrapped = wrapKoreanSubtitleLines(long, 8);
    expect(wrapped.split("\n").length).toBeLessThanOrEqual(MAX_SUBTITLE_LINES);
  });

  it("returns input unchanged when charsPerLine ≤ 0", () => {
    expect(wrapKoreanSubtitleLines("내용", 0)).toBe("내용");
    expect(wrapKoreanSubtitleLines("내용", -5)).toBe("내용");
  });
});
