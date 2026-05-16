import type { EditorClip } from "./types";
import { getClipDuration } from "./timeline-math";

export interface SourceTimeResult {
  clipIndex: number;
  videoId: string;
  sourceType: string;
  sourceMs: number;
}

/**
 * Map a timeline position to the source video position.
 * Returns null if the position is outside all clips (gap or past end).
 */
export function getSourceTime(
  clips: EditorClip[],
  timelineMs: number,
): SourceTimeResult | null {
  for (let i = 0; i < clips.length; i++) {
    const clip = clips[i];
    const clipEnd = clip.timelineStartMs + getClipDuration(clip);

    if (timelineMs >= clip.timelineStartMs && timelineMs < clipEnd) {
      const offsetInClip = timelineMs - clip.timelineStartMs;
      return {
        clipIndex: i,
        videoId: clip.videoId,
        sourceType: clip.sourceType,
        sourceMs: clip.trimStartMs + offsetInClip,
      };
    }
  }
  return null;
}

/**
 * Find the clip index at a given timeline position.
 * Returns -1 if no clip is found.
 */
export function getClipIndexAtTime(clips: EditorClip[], timelineMs: number): number {
  for (let i = 0; i < clips.length; i++) {
    const clip = clips[i];
    const clipEnd = clip.timelineStartMs + getClipDuration(clip);
    if (timelineMs >= clip.timelineStartMs && timelineMs < clipEnd) {
      return i;
    }
  }
  return -1;
}

/**
 * Get all subtitles active at a given timeline position.
 */
export function getActiveSubtitles<T extends { startMs: number; endMs: number }>(
  subtitles: T[],
  timelineMs: number,
): T[] {
  return subtitles.filter((s) => timelineMs >= s.startMs && timelineMs < s.endMs);
}
