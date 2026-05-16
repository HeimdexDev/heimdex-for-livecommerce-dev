import { describe, it, expect } from "vitest";
import {
  msToPixels,
  pixelsToMs,
  snapToGrid,
  getClipDuration,
  recomputeTimeline,
  getTotalDuration,
  formatTimelineTimestamp,
} from "../lib/timeline-math";
import type { EditorClip } from "../lib/types";

function makeClip(trimStart: number, trimEnd: number, id = "c"): EditorClip {
  return {
    id,
    sceneId: "s",
    videoId: "v",
    sourceType: "gdrive",
    originalStartMs: trimStart,
    originalEndMs: trimEnd,
    trimStartMs: trimStart,
    trimEndMs: trimEnd,
    timelineStartMs: 0,
    volume: 1.0,
  };
}

describe("msToPixels / pixelsToMs", () => {
  it("converts at default zoom (100 px/s)", () => {
    expect(msToPixels(1000, 100)).toBe(100);
    expect(msToPixels(2500, 100)).toBe(250);
    expect(pixelsToMs(100, 100)).toBe(1000);
    expect(pixelsToMs(250, 100)).toBe(2500);
  });

  it("converts at different zoom levels", () => {
    expect(msToPixels(1000, 50)).toBe(50);
    expect(msToPixels(1000, 200)).toBe(200);
    expect(pixelsToMs(50, 50)).toBe(1000);
  });

  it("handles zero zoom gracefully", () => {
    expect(pixelsToMs(100, 0)).toBe(0);
  });

  it("handles zero ms", () => {
    expect(msToPixels(0, 100)).toBe(0);
  });
});

describe("snapToGrid", () => {
  it("snaps to nearest grid point", () => {
    expect(snapToGrid(1200, 1000)).toBe(1000);
    expect(snapToGrid(1600, 1000)).toBe(2000);
    expect(snapToGrid(1500, 1000)).toBe(2000);
  });

  it("returns exact value when on grid", () => {
    expect(snapToGrid(3000, 1000)).toBe(3000);
  });

  it("returns input when gridMs is 0", () => {
    expect(snapToGrid(1234, 0)).toBe(1234);
  });
});

describe("getClipDuration", () => {
  it("returns trimmed duration", () => {
    const clip = makeClip(1000, 4000);
    expect(getClipDuration(clip)).toBe(3000);
  });
});

describe("recomputeTimeline", () => {
  it("assigns sequential timeline positions", () => {
    const clips = [makeClip(0, 2000, "a"), makeClip(5000, 8000, "b"), makeClip(0, 1000, "c")];
    const result = recomputeTimeline(clips);

    expect(result[0].timelineStartMs).toBe(0);
    expect(result[1].timelineStartMs).toBe(2000);
    expect(result[2].timelineStartMs).toBe(5000);
  });

  it("handles empty array", () => {
    expect(recomputeTimeline([])).toEqual([]);
  });

  it("handles single clip", () => {
    const result = recomputeTimeline([makeClip(100, 500)]);
    expect(result[0].timelineStartMs).toBe(0);
  });
});

describe("getTotalDuration", () => {
  it("returns sum of all clip durations", () => {
    const clips = recomputeTimeline([makeClip(0, 2000), makeClip(0, 3000)]);
    expect(getTotalDuration(clips)).toBe(5000);
  });

  it("returns 0 for empty array", () => {
    expect(getTotalDuration([])).toBe(0);
  });
});

describe("formatTimelineTimestamp", () => {
  it("formats seconds", () => {
    expect(formatTimelineTimestamp(0)).toBe("0:00");
    expect(formatTimelineTimestamp(5000)).toBe("0:05");
    expect(formatTimelineTimestamp(65000)).toBe("1:05");
  });

  it("formats with hours when needed", () => {
    expect(formatTimelineTimestamp(3661000)).toBe("1:01:01");
  });
});
