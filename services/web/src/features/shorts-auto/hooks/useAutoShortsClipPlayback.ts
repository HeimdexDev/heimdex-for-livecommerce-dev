"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getCloudPlaybackUrl } from "@/lib/agent";
import type { AutoClipResponse } from "@/lib/types";

interface UseClipPlaybackOptions {
  clip: AutoClipResponse | null;
  videoId: string;
}

interface ClipPlaybackHandlers {
  videoRef: React.RefObject<HTMLVideoElement>;
  /** ``null`` when no clip is loaded. */
  playbackUrl: string | null;
  isPlaying: boolean;
  /** 0-indexed; ``-1`` when nothing has played yet. */
  currentMemberIdx: number;
  /** Memoized ms duration so the UI can show "30초 / 45초" style readouts. */
  totalSourceDurationMs: number;
  togglePlay: () => void;
  /** Wire to the <video onLoadedMetadata>. Seeks to first member's start. */
  onLoadedMetadata: () => void;
  /** Wire to the <video onTimeUpdate>. Stitches members by jumping to next start. */
  onTimeUpdate: () => void;
  /** Wire to the <video onEnded>. Resets to start. */
  onEnded: () => void;
}

/**
 * Auto-shorts proxy-stitched playback.
 *
 * An ``AutoClipResponse`` is one short composed of N members — each a
 * span ``[start_ms, end_ms]`` inside the SAME source video. Members
 * are typically non-adjacent (LLM picks scenes from across the video),
 * so this hook plays them sequentially against the shared proxy URL
 * by seeking forward when the current member's ``end_ms`` is reached.
 *
 * Why not reuse ``features/shorts-editor/hooks/usePlaybackSync``: that
 * hook is built for a true multi-clip editor timeline (per-clip source
 * URLs, ``timelineStartMs``, RAF-driven playhead). Auto-shorts plays a
 * single video — adapter layer would have been more code than the hook
 * itself. This sticks to the surface area that AutoClipCard had pre-PR3
 * but lifts it out of the card so the new center-pane player can
 * consume it.
 *
 * Behavior:
 *  - On clip change: resets ``currentMemberIdx`` to 0, pauses, and
 *    queues a seek to the first member start (fires when the new src
 *    finishes loading, via ``onLoadedMetadata``).
 *  - On ``onTimeUpdate``: when current time ≥ current member ``end_ms``,
 *    advance to the next member and seek to its ``start_ms``. Past the
 *    last member: pause and reset.
 *  - On ``togglePlay``: start from the current position; if we're at
 *    end-of-clip, restart from member 0.
 */
export function useAutoShortsClipPlayback({
  clip,
  videoId,
}: UseClipPlaybackOptions): ClipPlaybackHandlers {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentMemberIdx, setCurrentMemberIdx] = useState(0);

  const playbackUrl = useMemo(() => {
    if (!clip || !videoId) return null;
    return getCloudPlaybackUrl(videoId, 0);
  }, [clip, videoId]);

  // Reset on clip swap. Pause, snap to first member; the actual seek
  // happens once the <video> reports loadedmetadata (different src has
  // different duration, so we can't seek before the metadata lands).
  useEffect(() => {
    setIsPlaying(false);
    setCurrentMemberIdx(0);
    const v = videoRef.current;
    if (v) v.pause();
  }, [clip?.scene_ids.join("-")]);

  const onLoadedMetadata = useCallback(() => {
    const v = videoRef.current;
    if (!v || !clip || clip.members.length === 0) return;
    v.currentTime = clip.members[0].start_ms / 1000;
  }, [clip]);

  const onTimeUpdate = useCallback(() => {
    const v = videoRef.current;
    if (!v || !clip) return;
    const members = clip.members;
    if (members.length === 0) return;

    const idx = currentMemberIdx;
    if (idx >= members.length) return;

    const nowMs = v.currentTime * 1000;
    const cur = members[idx];
    if (nowMs >= cur.end_ms) {
      const next = idx + 1;
      if (next < members.length) {
        setCurrentMemberIdx(next);
        v.currentTime = members[next].start_ms / 1000;
      } else {
        v.pause();
        setIsPlaying(false);
        setCurrentMemberIdx(0);
      }
    }
  }, [clip, currentMemberIdx]);

  const onEnded = useCallback(() => {
    setIsPlaying(false);
    setCurrentMemberIdx(0);
  }, []);

  const togglePlay = useCallback(() => {
    const v = videoRef.current;
    if (!v || !clip || clip.members.length === 0) return;

    if (isPlaying) {
      v.pause();
      setIsPlaying(false);
      return;
    }
    // Resume from current position; if we're past the last member, snap
    // back to the first so play always Just Works from any state.
    if (currentMemberIdx >= clip.members.length) {
      v.currentTime = clip.members[0].start_ms / 1000;
      setCurrentMemberIdx(0);
    }
    v.play().then(() => setIsPlaying(true)).catch(() => setIsPlaying(false));
  }, [clip, isPlaying, currentMemberIdx]);

  const totalSourceDurationMs = useMemo(() => {
    if (!clip) return 0;
    return clip.members.reduce(
      (sum, m) => sum + Math.max(0, m.end_ms - m.start_ms),
      0,
    );
  }, [clip]);

  return {
    videoRef,
    playbackUrl,
    isPlaying,
    currentMemberIdx,
    totalSourceDurationMs,
    togglePlay,
    onLoadedMetadata,
    onTimeUpdate,
    onEnded,
  };
}
