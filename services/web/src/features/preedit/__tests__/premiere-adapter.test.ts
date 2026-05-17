import { describe, expect, it } from "vitest";
import { buildPremiereRequest } from "../lib/premiere-adapter";
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
  videoTitle: null,
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

describe("buildPremiereRequest", () => {
  it("returns empty clips for project with no filled rows", () => {
    const project = makeProject([{ scene: null }]);
    const req = buildPremiereRequest(project, "/Volumes/Drive");
    expect(req.clips).toHaveLength(0);
  });

  it("maps filled rows to clips", () => {
    const project = makeProject([
      { scene: scene1, label: "Hook" },
      { scene: scene2, label: "Close-up" },
    ]);
    const req = buildPremiereRequest(project, "/Volumes/Drive");

    expect(req.clips).toHaveLength(2);
    expect(req.clips[0]).toEqual({
      scene_id: "scene-001",
      video_id: "video-a",
      video_title: "Video A",
      start_ms: 5000,
      end_ms: 15000,
      label: "Hook",
    });
    expect(req.clips[1].label).toBe("Close-up");
  });

  it("uses Row N fallback when label is empty", () => {
    const project = makeProject([{ scene: scene1 }, { scene: scene2 }]);
    const req = buildPremiereRequest(project, "/Volumes/Drive");

    expect(req.clips[0].label).toBe("Row 1");
    expect(req.clips[1].label).toBe("Row 2");
  });

  it("uses project title as sequence_name", () => {
    const project = makeProject([{ scene: scene1 }], "My Rough Cut");
    const req = buildPremiereRequest(project, "/Volumes/Drive");
    expect(req.sequence_name).toBe("My Rough Cut");
  });

  it("falls back to 가편집 when project title is empty", () => {
    const project = makeProject([{ scene: scene1 }], "");
    const req = buildPremiereRequest(project, "/Volumes/Drive");
    expect(req.sequence_name).toBe("가편집");
  });

  it("passes drive mount path through", () => {
    const project = makeProject([{ scene: scene1 }]);
    const req = buildPremiereRequest(project, "/Users/me/Google Drive");
    expect(req.drive_mount_path).toBe("/Users/me/Google Drive");
  });

  it("filters out unfilled rows", () => {
    const project = makeProject([
      { scene: scene1 },
      { scene: null },
      { scene: scene2 },
    ]);
    const req = buildPremiereRequest(project, "/Volumes/Drive");
    expect(req.clips).toHaveLength(2);
  });

  it("uses empty string for null video_title", () => {
    const project = makeProject([{ scene: scene2 }]);
    const req = buildPremiereRequest(project, "/Volumes/Drive");
    expect(req.clips[0].video_title).toBe("");
  });

  it("sets default export options", () => {
    const project = makeProject([{ scene: scene1 }]);
    const req = buildPremiereRequest(project, "/Volumes/Drive");
    expect(req.clip_gap_ms).toBe(0);
    expect(req.include_markers).toBe(true);
    expect(req.include_transcript_markers).toBe(false);
  });
});
