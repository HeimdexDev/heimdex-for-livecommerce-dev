import type { CompositionSpec } from "@/features/shorts-editor/lib/types";
import type { PreeditProject } from "./types";

export function buildPreeditComposition(
  project: PreeditProject,
  aspectRatio: "16:9" | "9:16",
): CompositionSpec {
  const filledRows = project.rows.filter((r) => r.selectedScene !== null);

  let timelineCursor = 0;
  const scene_clips = filledRows.map((row) => {
    const scene = row.selectedScene!;
    const duration = scene.endMs - scene.startMs;
    const clip = {
      scene_id: scene.sceneId,
      video_id: scene.videoId,
      source_type: scene.sourceType,
      start_ms: scene.startMs,
      end_ms: scene.endMs,
      timeline_start_ms: timelineCursor,
      volume: 1.0,
      crop_x: 0.0,
      crop_y: 0.0,
      crop_w: 1.0,
      crop_h: 1.0,
    };
    timelineCursor += duration;
    return clip;
  });

  const [width, height] =
    aspectRatio === "9:16" ? [1080, 1920] : [1920, 1080];

  return {
    overlays: [],
    output: {
      width,
      height,
      fps: 30,
      format: "mp4",
      background_color: "#000000",
    },
    scene_clips,
    subtitles: [],
    transitions: [],
    title: project.title || null,
    version: 1,
  };
}
