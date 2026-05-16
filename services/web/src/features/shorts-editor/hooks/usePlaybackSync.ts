import { useRef, useEffect, useCallback } from "react";
import { getAgentPlaybackUrl, getCloudPlaybackUrl } from "@/lib/agent";
import type { EditorClip } from "../lib/types";
import { getSourceTime } from "../lib/source-time";
import { getClipDuration } from "../lib/timeline-math";

interface PlaybackSyncOptions {
  clips: EditorClip[];
  playheadMs: number;
  isPlaying: boolean;
  onPlayheadChange: (ms: number) => void;
  onPlayingChange: (playing: boolean) => void;
  // playback rate (1.0 default, 1.5 fast). Optional so existing
  // callers don't need to pass it; applied to <video>.playbackRate.
  rate?: number;
}

function getVideoUrl(videoId: string, sourceType: string): string {
  if (sourceType === "gdrive") {
    return getCloudPlaybackUrl(videoId);
  }
  return getAgentPlaybackUrl(videoId);
}

/**
 * Syncs a <video> element with editor playhead state.
 * Handles multi-clip playback by switching video sources.
 */
export function usePlaybackSync({
  clips,
  playheadMs,
  isPlaying,
  onPlayheadChange,
  onPlayingChange,
  rate,
}: PlaybackSyncOptions) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const preloadRef = useRef<HTMLVideoElement>(null);
  const animFrameRef = useRef<number>(0);
  const lastSourceRef = useRef<{ videoId: string; url: string } | null>(null);
  const lastClipIndexRef = useRef<number>(-1);
  const seekingRef = useRef(false);
  const playheadAtStartRef = useRef(0);
  const startTimeRef = useRef(0);

  // Keep a ref to playheadMs so effects can read the latest value
  // without adding it to dependency arrays (avoids stale closures).
  const playheadMsRef = useRef(playheadMs);
  playheadMsRef.current = playheadMs;

  // Resolve current source from playhead
  const currentSource = getSourceTime(clips, playheadMs);
  const currentClipIndex = currentSource?.clipIndex ?? -1;

  // Load video source when clip changes (source switch only)
  useEffect(() => {
    const video = videoRef.current;
    if (!video || !currentSource) return;

    const url = getVideoUrl(currentSource.videoId, currentSource.sourceType);

    if (lastSourceRef.current?.url !== url) {
      lastSourceRef.current = { videoId: currentSource.videoId, url };
      video.src = url;
      video.load();
    }

    // Seek when clip index changes
    if (currentClipIndex !== lastClipIndexRef.current) {
      lastClipIndexRef.current = currentClipIndex;
      const targetTime = currentSource.sourceMs / 1000;
      seekingRef.current = true;
      video.currentTime = targetTime;
    }
  }, [currentClipIndex, currentSource?.videoId, currentSource?.sourceType]);

  // apply playbackRate whenever it changes or after a source reload.
  // Kept separate from seek/sync logic so playhead math stays untouched.
  // Browsers reset playbackRate to 1.0 on `video.src = ...; video.load()`,
  // so we re-apply on currentClipIndex change as well as rate change.
  useEffect(() => {
    if (videoRef.current && rate != null) {
      videoRef.current.playbackRate = rate;
    }
  }, [rate, currentClipIndex]);

  // Seek video when playhead changes while paused (user scrubbing)
  useEffect(() => {
    if (isPlaying || !currentSource || !videoRef.current) return;

    const targetTime = currentSource.sourceMs / 1000;
    if (Math.abs(videoRef.current.currentTime - targetTime) > 0.3) {
      videoRef.current.currentTime = targetTime;
    }
  }, [isPlaying, playheadMs, currentSource?.sourceMs]);

  // Preload next clip's video when playing
  useEffect(() => {
    if (!isPlaying || !currentSource || !preloadRef.current) return;

    const nextClipIndex = currentSource.clipIndex + 1;
    if (nextClipIndex >= clips.length) return;

    const nextClip = clips[nextClipIndex];
    const nextUrl = getVideoUrl(nextClip.videoId, nextClip.sourceType);

    if (preloadRef.current.src !== nextUrl) {
      preloadRef.current.src = nextUrl;
      preloadRef.current.preload = "auto";
    }
  }, [isPlaying, currentClipIndex, clips]);

  // Play/pause sync — reads playhead from ref to avoid stale closure
  useEffect(() => {
    const video = videoRef.current;
    const source = getSourceTime(clips, playheadMsRef.current);
    if (!video || !source) return;

    if (isPlaying) {
      playheadAtStartRef.current = playheadMsRef.current;
      startTimeRef.current = performance.now();

      const url = getVideoUrl(source.videoId, source.sourceType);
      if (lastSourceRef.current?.url !== url) {
        lastSourceRef.current = { videoId: source.videoId, url };
        video.src = url;
        video.load();
      }

      const targetTime = source.sourceMs / 1000;
      if (Math.abs(video.currentTime - targetTime) > 0.3) {
        video.currentTime = targetTime;
      }
      video.play().catch(() => {
        onPlayingChange(false);
      });
    } else {
      video.pause();
      cancelAnimationFrame(animFrameRef.current);
    }
  }, [isPlaying, clips, onPlayingChange]);

  // Animation frame loop for smooth playhead updates during playback
  useEffect(() => {
    if (!isPlaying) return;

    const tick = () => {
      const elapsed = performance.now() - startTimeRef.current;
      const newPlayhead = playheadAtStartRef.current + elapsed;

      // Check if we've gone past all clips
      const totalEnd = clips.length > 0
        ? clips[clips.length - 1].timelineStartMs + getClipDuration(clips[clips.length - 1])
        : 0;

      if (newPlayhead >= totalEnd) {
        onPlayheadChange(totalEnd);
        onPlayingChange(false);
        return;
      }

      // Check if we crossed into a new clip
      const newSource = getSourceTime(clips, newPlayhead);
      if (newSource && newSource.clipIndex !== lastClipIndexRef.current) {
        onPlayheadChange(newPlayhead);
        // Re-start timing from this point
        playheadAtStartRef.current = newPlayhead;
        startTimeRef.current = performance.now();
      } else {
        onPlayheadChange(newPlayhead);
      }

      animFrameRef.current = requestAnimationFrame(tick);
    };

    animFrameRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(animFrameRef.current);
  }, [isPlaying, clips, onPlayheadChange, onPlayingChange]);

  const onSeeked = useCallback(() => {
    seekingRef.current = false;
  }, []);

  const onEnded = useCallback(() => {
    if (!currentSource) return;
    const nextClipIndex = currentSource.clipIndex + 1;
    if (nextClipIndex < clips.length) {
      const nextClip = clips[nextClipIndex];
      onPlayheadChange(nextClip.timelineStartMs);
    } else {
      onPlayingChange(false);
    }
  }, [currentSource, clips, onPlayheadChange, onPlayingChange]);

  const seekTo = useCallback(
    (ms: number) => {
      onPlayheadChange(ms);
      const source = getSourceTime(clips, ms);
      if (source && videoRef.current) {
        const url = getVideoUrl(source.videoId, source.sourceType);
        if (lastSourceRef.current?.url !== url) {
          lastSourceRef.current = { videoId: source.videoId, url };
          videoRef.current.src = url;
          videoRef.current.load();
        }
        videoRef.current.currentTime = source.sourceMs / 1000;
      }
    },
    [clips, onPlayheadChange],
  );

  const togglePlay = useCallback(() => {
    onPlayingChange(!isPlaying);
  }, [isPlaying, onPlayingChange]);

  return {
    videoRef,
    preloadRef,
    currentSource,
    seekTo,
    togglePlay,
    onSeeked,
    onEnded,
  };
}
