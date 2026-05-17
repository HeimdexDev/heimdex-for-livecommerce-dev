import { describe, expect, it } from "vitest";
import { buildPreeditComposition } from "../lib/composition-adapter";
import type { PreeditProject, PreeditScene } from "../lib/types";

const scene1: PreeditScene = {
  sceneId: "scene-001",
  videoId: "video-a",
  sourceType: "gdrive",
  videoTitle: "Video A",
  startMs: 5000,
  endMs: 15000,
  snippet: "hello",
  keyframeTimestampMs: 7000,
};

const scene2: PreeditScene = {
  sceneId: "scene-002",
  videoId: "video-b",
  sourceType: "gdrive",
  videoTitle: "Video B",
  startMs: 20000,
  endMs: 35000,
  snippet: "world",
  keyframeTimestampMs: 22000,
};

function makeProject(
  rows: { scene: PreeditScene | null; label?: string }[],
  title = "",
): PreeditProject {
  return {
    id: "proj-1",
    title,
    rows: rows.map((r, i) => ({
      id: `row-${i}`,
      label: r.label ?? "",
      query: "",
      selectedScene: r.scene,
    })),
    createdAt: "2026-01-01T00:00:00.000Z",
    updatedAt: "2026-01-01T00:00:00.000Z",
  };
}

describe("buildPreeditComposition", () => {
  it("returns empty scene_clips for project with no filled rows", () => {
    const project = makeProject([{ scene: null }, { scene: null }]);
    const spec = buildPreeditComposition(project, "16:9");
    expect(spec.scene_clips).toHaveLength(0);
    expect(spec.output.width).toBe(1920);
    expect(spec.output.height).toBe(1080);
  });

  it("builds single clip with timeline_start_ms 0", () => {
    const project = makeProject([{ scene: scene1 }]);
    const spec = buildPreeditComposition(project, "16:9");

    expect(spec.scene_clips).toHaveLength(1);
    const clip = spec.scene_clips[0];
    expect(clip.scene_id).toBe("scene-001");
    expect(clip.video_id).toBe("video-a");
    expect(clip.start_ms).toBe(5000);
    expect(clip.end_ms).toBe(15000);
    expect(clip.timeline_start_ms).toBe(0);
    expect(clip.volume).toBe(1.0);
  });

  it("builds sequential timeline_start_ms for multiple clips", () => {
    const project = makeProject([{ scene: scene1 }, { scene: scene2 }]);
    const spec = buildPreeditComposition(project, "16:9");

    expect(spec.scene_clips).toHaveLength(2);
    expect(spec.scene_clips[0].timeline_start_ms).toBe(0);
    // scene1 duration = 15000 - 5000 = 10000ms
    expect(spec.scene_clips[1].timeline_start_ms).toBe(10000);
  });

  it("filters out unfilled rows", () => {
    const project = makeProject([
      { scene: scene1 },
      { scene: null },
      { scene: scene2 },
    ]);
    const spec = buildPreeditComposition(project, "16:9");

    expect(spec.scene_clips).toHaveLength(2);
    expect(spec.scene_clips[0].scene_id).toBe("scene-001");
    expect(spec.scene_clips[1].scene_id).toBe("scene-002");
  });

  it("supports multi-video (different video_id per clip)", () => {
    const project = makeProject([{ scene: scene1 }, { scene: scene2 }]);
    const spec = buildPreeditComposition(project, "16:9");

    expect(spec.scene_clips[0].video_id).toBe("video-a");
    expect(spec.scene_clips[1].video_id).toBe("video-b");
  });

  it("uses 1920x1080 for 16:9 aspect ratio", () => {
    const project = makeProject([{ scene: scene1 }]);
    const spec = buildPreeditComposition(project, "16:9");

    expect(spec.output.width).toBe(1920);
    expect(spec.output.height).toBe(1080);
  });

  it("uses 1080x1920 for 9:16 aspect ratio", () => {
    const project = makeProject([{ scene: scene1 }]);
    const spec = buildPreeditComposition(project, "9:16");

    expect(spec.output.width).toBe(1080);
    expect(spec.output.height).toBe(1920);
  });

  it("maps project title to composition title", () => {
    const project = makeProject([{ scene: scene1 }], "My Rough Cut");
    const spec = buildPreeditComposition(project, "16:9");

    expect(spec.title).toBe("My Rough Cut");
  });

  it("sets title to null when project title is empty", () => {
    const project = makeProject([{ scene: scene1 }], "");
    const spec = buildPreeditComposition(project, "16:9");

    expect(spec.title).toBeNull();
  });

  it("sets full frame crop on all clips", () => {
    const project = makeProject([{ scene: scene1 }]);
    const spec = buildPreeditComposition(project, "16:9");

    const clip = spec.scene_clips[0];
    expect(clip.crop_x).toBe(0.0);
    expect(clip.crop_y).toBe(0.0);
    expect(clip.crop_w).toBe(1.0);
    expect(clip.crop_h).toBe(1.0);
  });

  it("has empty subtitles and transitions", () => {
    const project = makeProject([{ scene: scene1 }]);
    const spec = buildPreeditComposition(project, "16:9");

    expect(spec.subtitles).toEqual([]);
    expect(spec.transitions).toEqual([]);
    expect(spec.version).toBe(1);
  });
});
