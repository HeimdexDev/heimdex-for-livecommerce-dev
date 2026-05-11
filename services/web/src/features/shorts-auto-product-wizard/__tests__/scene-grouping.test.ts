import { describe, expect, it } from "vitest";

import {
  groupCuesByScene,
  type SceneClipForGrouping,
} from "../lib/scene-grouping";
import type { SubtitleEdit } from "@/lib/api/highlight-reel";

function makeCue(start: number, end: number, text = "cue"): SubtitleEdit {
  return { text, start_ms: start, end_ms: end };
}

function makeScene(
  id: string,
  sourceStart: number,
  sourceEnd: number,
  timelineStart?: number,
): SceneClipForGrouping {
  return {
    scene_id: id,
    start_ms: sourceStart,
    end_ms: sourceEnd,
    timeline_start_ms: timelineStart,
  };
}

describe("groupCuesByScene", () => {
  it("returns empty groups + every cue as out-of-bounds when no scenes", () => {
    const cues = [makeCue(0, 1000)];
    const { groups, outOfBounds } = groupCuesByScene(cues, []);
    expect(groups).toEqual([]);
    expect(outOfBounds).toEqual(cues);
  });

  it("buckets each cue under the scene whose timeline range contains its start", () => {
    const scenes = [
      makeScene("s1", 0, 5000, 0), // [0, 5000) output
      makeScene("s2", 5000, 10000, 5000), // [5000, 10000)
    ];
    const cues = [makeCue(100, 800), makeCue(6000, 7000)];
    const { groups, outOfBounds } = groupCuesByScene(cues, scenes);
    expect(outOfBounds).toEqual([]);
    expect(groups).toHaveLength(2);
    expect(groups[0].sceneId).toBe("s1");
    expect(groups[0].sceneIndex).toBe(1);
    expect(groups[0].cues).toHaveLength(1);
    expect(groups[0].cues[0].start_ms).toBe(100);
    expect(groups[1].sceneId).toBe("s2");
    expect(groups[1].sceneIndex).toBe(2);
    expect(groups[1].cues).toHaveLength(1);
    expect(groups[1].cues[0].start_ms).toBe(6000);
  });

  it("multiple cues in the same scene preserve insertion order", () => {
    const scenes = [makeScene("s1", 0, 10000, 0)];
    const cues = [makeCue(2000, 3000, "b"), makeCue(500, 1500, "a")];
    const { groups } = groupCuesByScene(cues, scenes);
    expect(groups[0].cues.map((c) => c.text)).toEqual(["b", "a"]);
  });

  it("an empty scene with no overlapping cues yields an empty cue list (header still rendered)", () => {
    const scenes = [
      makeScene("s1", 0, 5000, 0),
      makeScene("s2", 5000, 10000, 5000),
    ];
    const cues = [makeCue(100, 800)];
    const { groups } = groupCuesByScene(cues, scenes);
    expect(groups[1].cues).toHaveLength(0);
    expect(groups[1].sceneId).toBe("s2");
  });

  it("cue with start exactly at scene boundary lands in the LATER scene", () => {
    const scenes = [
      makeScene("s1", 0, 5000, 0),
      makeScene("s2", 5000, 10000, 5000),
    ];
    const cues = [makeCue(5000, 5500)];
    const { groups } = groupCuesByScene(cues, scenes);
    expect(groups[0].cues).toHaveLength(0);
    expect(groups[1].cues).toHaveLength(1);
  });

  it("a cue starting outside every scene's range goes to outOfBounds", () => {
    const scenes = [makeScene("s1", 0, 5000, 0)];
    const cues = [makeCue(10000, 11000)];
    const { groups, outOfBounds } = groupCuesByScene(cues, scenes);
    expect(groups[0].cues).toHaveLength(0);
    expect(outOfBounds).toHaveLength(1);
  });

  it("missing timeline_start_ms falls back to cumulative duration from preceding scenes", () => {
    const scenes = [
      makeScene("s1", 0, 3000), // no timeline_start_ms → 0
      makeScene("s2", 0, 4000), // no timeline_start_ms → 3000
    ];
    const cues = [makeCue(1000, 2000), makeCue(5000, 6000)];
    const { groups } = groupCuesByScene(cues, scenes);
    expect(groups[0].startMs).toBe(0);
    expect(groups[0].endMs).toBe(3000);
    expect(groups[1].startMs).toBe(3000);
    expect(groups[1].endMs).toBe(7000);
    expect(groups[0].cues).toHaveLength(1);
    expect(groups[1].cues).toHaveLength(1);
  });
});
