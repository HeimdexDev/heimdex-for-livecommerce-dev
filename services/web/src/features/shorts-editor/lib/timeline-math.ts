import type { EditorClip } from "./types";

export {
  msToPixels,
  pixelsToMs,
  snapToGrid,
  formatTimelineTimestamp,
  formatVideoTimestampHMS,
} from "@/lib/timeline";

export function getClipDuration(clip: EditorClip): number {
  return clip.trimEndMs - clip.trimStartMs;
}

export function recomputeTimeline(clips: EditorClip[]): EditorClip[] {
  let offset = 0;
  return clips.map((clip) => {
    const updated = { ...clip, timelineStartMs: offset };
    offset += getClipDuration(clip);
    return updated;
  });
}

export function getTotalDuration(clips: EditorClip[]): number {
  if (clips.length === 0) return 0;
  const last = clips[clips.length - 1];
  return last.timelineStartMs + getClipDuration(last);
}
