import { describe, it, expect } from "vitest";
import { dotColorForLabel } from "../speaker-transcript-display";

describe("dotColorForLabel", () => {
  it("maps Speaker A to red and B to green per Figma", () => {
    expect(dotColorForLabel("A")).toBe("bg-red-500");
    expect(dotColorForLabel("B")).toBe("bg-emerald-500");
  });

  it("cycles through palette for additional speakers", () => {
    expect(dotColorForLabel("C")).toBe("bg-blue-500");
    expect(dotColorForLabel("D")).toBe("bg-amber-500");
    expect(dotColorForLabel("E")).toBe("bg-violet-500");
    expect(dotColorForLabel("F")).toBe("bg-cyan-500");
  });

  it("wraps past the palette length", () => {
    // 'G' is index 6 in a 6-color palette → wraps to first color (red).
    expect(dotColorForLabel("G")).toBe("bg-red-500");
  });

  it("falls back to first color for unrecognized labels", () => {
    expect(dotColorForLabel("")).toBe("bg-red-500");
    expect(dotColorForLabel("?")).toBe("bg-red-500");
  });
});
