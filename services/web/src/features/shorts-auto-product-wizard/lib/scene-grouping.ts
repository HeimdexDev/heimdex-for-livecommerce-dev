// ============================================================================
// Pure helper: group `SubtitleEdit[]` cues under the scene boundaries that
// produced them. Used by the 자막 tab to render scene headers
// ("장면N MM:SS – MM:SS Ns") above each scene's cues per Figma.
//
// A cue belongs to a scene when its ``start_ms`` falls within the scene's
// rendered timeline range. The composition's ``scene_clips`` carry
// ``timeline_start_ms`` (when the scene begins inside the output MP4) plus
// per-scene ``start_ms`` / ``end_ms`` (source video range). The cue's
// ``start_ms`` is in *output* time, so we use the scene's
// ``timeline_start_ms`` + duration to bucket.
//
// Out-of-bounds cues (post-fan-out edits that fall past every scene) land
// in a synthetic "이외" group so bugs surface loudly rather than dropping
// cues silently.
// ============================================================================

import type { SubtitleEdit } from "@/lib/api/highlight-reel";

export interface SceneClipForGrouping {
  scene_id: string;
  /** Source video start (unused for bucketing but useful for debugging). */
  start_ms: number;
  /** Source video end. */
  end_ms: number;
  /**
   * When this scene begins in the output MP4 timeline. Optional — legacy
   * compositions may not have it set. Falls back to 0 + cumulative duration.
   */
  timeline_start_ms?: number;
}

export interface SceneCueGroup {
  sceneId: string;
  /** 1-based index for "장면N" display. */
  sceneIndex: number;
  /** Inclusive lower bound in output timeline ms. */
  startMs: number;
  /** Exclusive upper bound in output timeline ms. */
  endMs: number;
  /** ``endMs - startMs`` — convenience for "Ns" header copy. */
  durationMs: number;
  cues: SubtitleEdit[];
}

const FALLBACK_GROUP_ID = "__out_of_bounds__";

interface GroupingResult {
  groups: SceneCueGroup[];
  /** Cues that didn't fall into any scene's range. */
  outOfBounds: SubtitleEdit[];
}

/**
 * Group cues by scene boundaries.
 *
 * Resolves missing ``timeline_start_ms`` by computing cumulative duration
 * from preceding scenes (start_ms/end_ms span). Output groups preserve
 * scene order regardless of cue order.
 *
 * The fallback "이외" group is intentionally exposed as a separate field
 * so callers can surface a banner when it's non-empty (almost certainly a
 * bug worth investigating).
 */
export function groupCuesByScene(
  cues: SubtitleEdit[],
  sceneClips: SceneClipForGrouping[],
): GroupingResult {
  if (sceneClips.length === 0) {
    return { groups: [], outOfBounds: [...cues] };
  }

  // Resolve effective timeline ranges. Each scene starts where the previous
  // one ended on the output timeline (concat semantics from the renderer).
  let cursor = 0;
  const ranges = sceneClips.map((sc, idx) => {
    const sceneDuration = Math.max(0, sc.end_ms - sc.start_ms);
    const explicitStart = sc.timeline_start_ms;
    const startMs = explicitStart ?? cursor;
    const endMs = startMs + sceneDuration;
    cursor = endMs;
    return {
      sceneId: sc.scene_id,
      sceneIndex: idx + 1,
      startMs,
      endMs,
      durationMs: sceneDuration,
    };
  });

  // Build empty groups in scene order so the result matches scene_clips ordering.
  const groupByScene = new Map<string, SceneCueGroup>();
  for (const r of ranges) {
    groupByScene.set(r.sceneId, {
      ...r,
      cues: [],
    });
  }

  const outOfBounds: SubtitleEdit[] = [];
  for (const cue of cues) {
    const owner = ranges.find(
      (r) => cue.start_ms >= r.startMs && cue.start_ms < r.endMs,
    );
    if (!owner) {
      outOfBounds.push(cue);
      continue;
    }
    groupByScene.get(owner.sceneId)?.cues.push(cue);
  }

  // Preserve insertion order from sceneClips. The map insertion order
  // matches ranges, which matches sceneClips, so this is stable.
  const groups = Array.from(groupByScene.values());
  return { groups, outOfBounds };
}

export { FALLBACK_GROUP_ID };
