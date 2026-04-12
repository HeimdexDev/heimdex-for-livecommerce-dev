import type { PremierePackageRequest } from "@/lib/cloud-export";
import type { PreeditProject } from "./types";

export function buildPremiereRequest(
  project: PreeditProject,
  driveMountPath: string,
): PremierePackageRequest {
  const filledRows = project.rows.filter((r) => r.selectedScene !== null);

  const clips = filledRows.map((row, i) => {
    const scene = row.selectedScene!;
    return {
      scene_id: scene.sceneId,
      video_id: scene.videoId,
      video_title: scene.videoTitle ?? "",
      start_ms: scene.startMs,
      end_ms: scene.endMs,
      label: row.label || `Row ${i + 1}`,
    };
  });

  return {
    sequence_name: project.title || "가편집",
    drive_mount_path: driveMountPath,
    clips,
    clip_gap_ms: 0,
    include_markers: true,
    include_transcript_markers: false,
  };
}
