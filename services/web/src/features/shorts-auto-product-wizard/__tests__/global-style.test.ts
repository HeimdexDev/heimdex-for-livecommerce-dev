import { describe, expect, it } from "vitest";

import {
  applyGlobalStyleToCues,
  deriveGlobalStyle,
  makeDefaultStyle,
  mergeStyle,
  type SubtitleStyleDraft,
} from "../lib/global-style";
import type { SubtitleEdit } from "@/lib/api/highlight-reel";

const BASE: SubtitleStyleDraft = makeDefaultStyle();

function styledCue(style: Partial<SubtitleStyleDraft> = {}): SubtitleEdit {
  return {
    text: "cue",
    start_ms: 0,
    end_ms: 1000,
    style: { ...BASE, ...style },
  };
}

describe("makeDefaultStyle", () => {
  it("returns Pretendard center-aligned bold white-on-white-pill defaults", () => {
    const d = makeDefaultStyle();
    expect(d.font_family).toBe("Pretendard");
    expect(d.text_align).toBe("center");
    expect(d.font_weight).toBe(700);
    expect(d.font_color).toBe("#000000");
    expect(d.background_color).toBe("#FFFFFF");
    expect(d.background_opacity).toBeCloseTo(0.95);
    expect(d.position_y).toBeCloseTo(0.82);
  });
});

describe("deriveGlobalStyle", () => {
  it("returns null for empty cues", () => {
    expect(deriveGlobalStyle([])).toBeNull();
  });

  it("returns the shared style when every cue agrees", () => {
    const cues = [styledCue(), styledCue(), styledCue()];
    const derived = deriveGlobalStyle(cues);
    expect(derived).not.toBeNull();
    expect(derived?.font_color).toBe(BASE.font_color);
  });

  it("returns null when cues have mixed styles", () => {
    const cues = [styledCue(), styledCue({ font_color: "#FF0000" })];
    expect(deriveGlobalStyle(cues)).toBeNull();
  });

  it("returns null when a cue is missing its style field", () => {
    const cues = [styledCue(), { text: "x", start_ms: 0, end_ms: 100 }];
    expect(deriveGlobalStyle(cues)).toBeNull();
  });

  it("returns null when a cue's style has the wrong shape (e.g. missing field)", () => {
    const cues: SubtitleEdit[] = [
      {
        text: "x",
        start_ms: 0,
        end_ms: 100,
        style: { font_family: "Pretendard" }, // missing everything else
      },
    ];
    expect(deriveGlobalStyle(cues)).toBeNull();
  });
});

describe("applyGlobalStyleToCues", () => {
  it("writes the same style to every cue", () => {
    const original: SubtitleEdit[] = [
      { text: "a", start_ms: 0, end_ms: 100 },
      { text: "b", start_ms: 100, end_ms: 200, style: { font_color: "#0000FF" } },
    ];
    const next = applyGlobalStyleToCues(original, BASE);
    expect(next).toHaveLength(2);
    expect(next[0].text).toBe("a");
    expect((next[0].style as { font_color: string }).font_color).toBe(
      BASE.font_color,
    );
    expect((next[1].style as { font_color: string }).font_color).toBe(
      BASE.font_color,
    );
  });

  it("returns a fresh array (no in-place mutation)", () => {
    const original: SubtitleEdit[] = [{ text: "a", start_ms: 0, end_ms: 1 }];
    const next = applyGlobalStyleToCues(original, BASE);
    expect(next).not.toBe(original);
    expect(next[0]).not.toBe(original[0]);
    expect(original[0].style).toBeUndefined();
  });
});

describe("mergeStyle", () => {
  it("overlays partial fields onto base style", () => {
    const merged = mergeStyle(BASE, { font_color: "#FF0000" });
    expect(merged.font_color).toBe("#FF0000");
    expect(merged.font_family).toBe(BASE.font_family);
  });

  it("does not mutate the base style", () => {
    const before = { ...BASE };
    mergeStyle(BASE, { font_color: "#FF0000" });
    expect(BASE).toEqual(before);
  });
});
