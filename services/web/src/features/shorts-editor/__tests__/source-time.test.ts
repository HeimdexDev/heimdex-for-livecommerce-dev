import { describe, it, expect } from "vitest";
import { getSourceTime, getClipIndexAtTime, getActiveSubtitles } from "../lib/source-time";
import { recomputeTimeline } from "../lib/timeline-math";
import type { EditorClip } from "../lib/types";

function makeClip(trimStart: number, trimEnd: number, videoId = "v1", id = "c"): EditorClip {
  return {
    id,
    sceneId: "s",
    videoId,
    sourceType: "gdrive",
    originalStartMs: trimStart,
    originalEndMs: trimEnd,
    trimStartMs: trimStart,
    trimEndMs: trimEnd,
    timelineStartMs: 0,
    volume: 1.0,
  };
}

describe("getSourceTime", () => {
  it("maps timeline position to source position in single clip", () => {
    const clips = recomputeTimeline([makeClip(5000, 10000, "v1", "c1")]);
    const result = getSourceTime(clips, 2000);

    expect(result).not.toBeNull();
    expect(result!.clipIndex).toBe(0);
    expect(result!.videoId).toBe("v1");
    expect(result!.sourceMs).toBe(7000); // 5000 + 2000
  });

  it("maps across multiple clips", () => {
    const clips = recomputeTimeline([
      makeClip(0, 3000, "v1", "c1"),
      makeClip(10000, 15000, "v2", "c2"),
    ]);

    // In clip 1
    const r1 = getSourceTime(clips, 1000);
    expect(r1!.clipIndex).toBe(0);
    expect(r1!.sourceMs).toBe(1000);

    // In clip 2 (timeline 3000 = start of clip 2)
    const r2 = getSourceTime(clips, 4000);
    expect(r2!.clipIndex).toBe(1);
    expect(r2!.videoId).toBe("v2");
    expect(r2!.sourceMs).toBe(11000); // 10000 + (4000-3000)
  });

  it("returns null for position past all clips", () => {
    const clips = recomputeTimeline([makeClip(0, 2000)]);
    expect(getSourceTime(clips, 5000)).toBeNull();
  });

  it("returns null for empty clips", () => {
    expect(getSourceTime([], 0)).toBeNull();
  });
});

describe("getClipIndexAtTime", () => {
  it("returns correct index", () => {
    const clips = recomputeTimeline([makeClip(0, 2000, "v", "a"), makeClip(0, 3000, "v", "b")]);
    expect(getClipIndexAtTime(clips, 0)).toBe(0);
    expect(getClipIndexAtTime(clips, 1999)).toBe(0);
    expect(getClipIndexAtTime(clips, 2000)).toBe(1);
    expect(getClipIndexAtTime(clips, 4999)).toBe(1);
  });

  it("returns -1 past end", () => {
    const clips = recomputeTimeline([makeClip(0, 1000)]);
    expect(getClipIndexAtTime(clips, 1000)).toBe(-1);
  });
});

describe("getActiveSubtitles", () => {
  it("returns subtitles within time range", () => {
    const subs = [
      { startMs: 0, endMs: 2000, text: "a" },
      { startMs: 1000, endMs: 3000, text: "b" },
      { startMs: 5000, endMs: 7000, text: "c" },
    ];

    expect(getActiveSubtitles(subs, 1500)).toHaveLength(2);
    expect(getActiveSubtitles(subs, 500)).toHaveLength(1);
    expect(getActiveSubtitles(subs, 4000)).toHaveLength(0);
    expect(getActiveSubtitles(subs, 6000)).toHaveLength(1);
  });

  it("returns empty for empty array", () => {
    expect(getActiveSubtitles([], 0)).toHaveLength(0);
  });
});
