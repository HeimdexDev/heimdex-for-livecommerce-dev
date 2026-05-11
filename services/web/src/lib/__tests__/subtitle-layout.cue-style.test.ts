// ============================================================================
// Tests for the per-cue style resolver in subtitle-layout.ts.
//
// Plan: .claude/plans/wysiwyg-subtitle-overlay-2026-05-11.md (Phase 1).
//
// The resolver is the pure-data layer that translates a partial
// SubtitleCueStyle (per the contracts SubtitleStyleSpec) into CSS-ready
// values, scaling canvas pixels into rendered pixels. <SubtitleOverlay>
// will consume it in Phase 2; these tests lock the resolver behavior
// independently so the overlay can be refactored without breaking
// semantics.
//
// Test invariants:
//   - Null cueStyle + canvas-defaults-to-rendered ⇒ values identical to
//     today's <SubtitleOverlay> output (backward compatibility gate).
//   - Per-field overrides flow through and scale correctly.
//   - Null colors (background/stroke/shadow) suppress the respective
//     CSS output (mirrors drawtext's `has_*` semantics).
// ============================================================================

import { describe, expect, it } from "vitest";

import { resolveOverlayStyle } from "@/lib/subtitle-layout";

describe("resolveOverlayStyle — null cueStyle", () => {
  it("matches today's overlay defaults at rendered=canvas=720", () => {
    const r = resolveOverlayStyle({
      cueStyle: null,
      renderedWidth: 406,
      renderedHeight: 720,
    });
    // Mirrors <SubtitleOverlay> defaults: black-bold on white pill,
    // 32px font at 720p, centered, position_y=0.82.
    expect(r.fontSizePx).toBe(32);
    expect(r.paddingPx).toBe(11);
    expect(r.fontWeight).toBe(700);
    expect(r.fontColor).toBe("#000000");
    expect(r.textAlign).toBe("center");
    expect(r.positionX).toBe(0.5);
    expect(r.positionY).toBe(0.82);
    expect(r.background).toBe("rgba(255, 255, 255, 0.95)");
    expect(r.webkitTextStroke).toBeNull();
    expect(r.textShadow).toBeNull();
    expect(r.fontFamily).toContain("Pretendard");
    expect(r.charsPerLine).toBe(11);
  });

  it("treats rendered as canvas when canvas dims omitted (legacy path)", () => {
    // 1080 * 0.045 = 48.6 → 49. Mirrors the existing
    // <SubtitleOverlay> test "scales font size with rendered video height".
    const r = resolveOverlayStyle({
      cueStyle: null,
      renderedWidth: 609,
      renderedHeight: 1080,
    });
    expect(r.fontSizePx).toBe(49);
    expect(r.paddingPx).toBe(16);
  });

  it("uses default canvas (720) values when canvasHeight is explicit", () => {
    const r = resolveOverlayStyle({
      cueStyle: null,
      canvasWidth: 406,
      canvasHeight: 720,
      renderedWidth: 406,
      renderedHeight: 720,
    });
    expect(r.fontSizePx).toBe(32);
  });
});

describe("resolveOverlayStyle — scale factor", () => {
  it("scales canvas-pixel fields by renderedHeight / canvasHeight", () => {
    const r = resolveOverlayStyle({
      cueStyle: {
        font_size_px: 40,
        background_padding: 10,
        stroke_color: "#FF0000",
        stroke_width: 2,
        shadow_enabled: true,
        shadow_color: "#000000",
        shadow_offset_x: 4,
        shadow_offset_y: 4,
      },
      canvasWidth: 720,
      canvasHeight: 720,
      renderedWidth: 1440,
      renderedHeight: 1440, // 2× scale
    });
    expect(r.fontSizePx).toBe(80); // 40 * 2
    expect(r.paddingPx).toBe(20); // 10 * 2
    expect(r.webkitTextStroke).toBe("4px #FF0000"); // 2 * 2
    expect(r.textShadow).toBe("8px 8px 0 #000000"); // 4 * 2
  });

  it("leaves normalized fields (position_x/y, opacity) unchanged by scale", () => {
    const r = resolveOverlayStyle({
      cueStyle: {
        position_x: 0.25,
        position_y: 0.75,
        background_color: "#000000",
        background_opacity: 0.5,
      },
      canvasWidth: 720,
      canvasHeight: 720,
      renderedWidth: 1080,
      renderedHeight: 1080,
    });
    expect(r.positionX).toBe(0.25);
    expect(r.positionY).toBe(0.75);
    expect(r.background).toBe("rgba(0, 0, 0, 0.5)");
  });

  it("derives charsPerLine from CANVAS dims (matches drawtext wrap budget)", () => {
    // charsPerLine is wrap-budget — should be invariant to rendered
    // size. canvas=406x720, font=32, padding=11 → 11 chars/line
    // (same as `subtitle-layout.test.ts`).
    const r = resolveOverlayStyle({
      cueStyle: null,
      canvasWidth: 406,
      canvasHeight: 720,
      renderedWidth: 812,
      renderedHeight: 1440,
    });
    expect(r.charsPerLine).toBe(11);
  });
});

describe("resolveOverlayStyle — per-field overrides", () => {
  it("honors font_color override", () => {
    const r = resolveOverlayStyle({
      cueStyle: { font_color: "#FF3B30" },
      renderedWidth: 406,
      renderedHeight: 720,
    });
    expect(r.fontColor).toBe("#FF3B30");
  });

  it("honors font_weight override", () => {
    const r = resolveOverlayStyle({
      cueStyle: { font_weight: 400 },
      renderedWidth: 406,
      renderedHeight: 720,
    });
    expect(r.fontWeight).toBe(400);
  });

  it("honors text_align override", () => {
    const r = resolveOverlayStyle({
      cueStyle: { text_align: "right" },
      renderedWidth: 406,
      renderedHeight: 720,
    });
    expect(r.textAlign).toBe("right");
  });

  it("honors position override", () => {
    const r = resolveOverlayStyle({
      cueStyle: { position_x: 0.95, position_y: 0.1 },
      renderedWidth: 406,
      renderedHeight: 720,
    });
    expect(r.positionX).toBe(0.95);
    expect(r.positionY).toBe(0.1);
  });

  it("emits rgba background from hex + opacity", () => {
    const r = resolveOverlayStyle({
      cueStyle: { background_color: "#112233", background_opacity: 0.6 },
      renderedWidth: 406,
      renderedHeight: 720,
    });
    expect(r.background).toBe("rgba(17, 34, 51, 0.6)");
  });

  it("emits null background when cue's background_color is null", () => {
    const r = resolveOverlayStyle({
      cueStyle: { background_color: null },
      renderedWidth: 406,
      renderedHeight: 720,
    });
    expect(r.background).toBeNull();
  });

  it("emits stroke only when stroke_color set and stroke_width > 0", () => {
    const set = resolveOverlayStyle({
      cueStyle: { stroke_color: "#FF0000", stroke_width: 2 },
      renderedWidth: 406,
      renderedHeight: 720,
    });
    expect(set.webkitTextStroke).toBe("2px #FF0000");

    const zeroWidth = resolveOverlayStyle({
      cueStyle: { stroke_color: "#FF0000", stroke_width: 0 },
      renderedWidth: 406,
      renderedHeight: 720,
    });
    expect(zeroWidth.webkitTextStroke).toBeNull();

    const nullColor = resolveOverlayStyle({
      cueStyle: { stroke_color: null, stroke_width: 5 },
      renderedWidth: 406,
      renderedHeight: 720,
    });
    expect(nullColor.webkitTextStroke).toBeNull();
  });

  it("emits shadow only when enabled AND color set", () => {
    const enabled = resolveOverlayStyle({
      cueStyle: {
        shadow_enabled: true,
        shadow_color: "#000000",
        shadow_offset_x: 2,
        shadow_offset_y: 3,
      },
      renderedWidth: 406,
      renderedHeight: 720,
    });
    expect(enabled.textShadow).toBe("2px 3px 0 #000000");

    const disabled = resolveOverlayStyle({
      cueStyle: {
        shadow_enabled: false,
        shadow_color: "#000000",
        shadow_offset_x: 2,
        shadow_offset_y: 3,
      },
      renderedWidth: 406,
      renderedHeight: 720,
    });
    expect(disabled.textShadow).toBeNull();

    const noColor = resolveOverlayStyle({
      cueStyle: {
        shadow_enabled: true,
        shadow_color: null,
        shadow_offset_x: 2,
        shadow_offset_y: 3,
      },
      renderedWidth: 406,
      renderedHeight: 720,
    });
    expect(noColor.textShadow).toBeNull();
  });

  it("falls back to Pretendard for missing font_family", () => {
    const r = resolveOverlayStyle({
      cueStyle: null,
      renderedWidth: 406,
      renderedHeight: 720,
    });
    expect(r.fontFamily.startsWith('"Pretendard"')).toBe(true);
  });

  it("uses Noto Sans KR when specified", () => {
    const r = resolveOverlayStyle({
      cueStyle: { font_family: "Noto Sans KR" },
      renderedWidth: 406,
      renderedHeight: 720,
    });
    expect(r.fontFamily.startsWith('"Noto Sans KR"')).toBe(true);
  });
});

describe("resolveOverlayStyle — defensive parsing", () => {
  it("returns rgba(255,255,255,opacity) for malformed hex (keeps overlay visible)", () => {
    const r = resolveOverlayStyle({
      cueStyle: { background_color: "not-a-hex", background_opacity: 0.4 },
      renderedWidth: 406,
      renderedHeight: 720,
    });
    expect(r.background).toBe("rgba(255, 255, 255, 0.4)");
  });

  it("clamps non-positive rendered dims to 1px to avoid div-by-zero", () => {
    const r = resolveOverlayStyle({
      cueStyle: null,
      renderedWidth: 0,
      renderedHeight: 0,
    });
    // fontSizePx >= 1 by clamp; exact value is implementation detail
    // (canvas defaults to renderedHeight=1, ratio 0.045 → floor 16 →
    // scaled by 1 → 16).
    expect(r.fontSizePx).toBeGreaterThanOrEqual(1);
  });

  it("scales stroke width down to 0 when below half a rendered pixel", () => {
    // canvas=720, rendered=72 (10× shrink). stroke_width=2 canvas →
    // round(2 * 0.1) = 0. has_stroke=false ⇒ null.
    const r = resolveOverlayStyle({
      cueStyle: { stroke_color: "#000000", stroke_width: 2 },
      canvasWidth: 720,
      canvasHeight: 720,
      renderedWidth: 72,
      renderedHeight: 72,
    });
    expect(r.webkitTextStroke).toBeNull();
  });
});
