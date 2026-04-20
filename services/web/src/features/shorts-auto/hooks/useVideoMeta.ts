"use client";

import { useEffect, useState } from "react";

import { getVideoScenes } from "@/lib/api/videos";
import type { VideoScenesResponse } from "@/lib/types";

type TokenGetter = () => Promise<string | null>;

interface State {
  meta: VideoScenesResponse | null;
  isLoading: boolean;
  error: Error | null;
}

/**
 * Load a video's scene metadata once for rendering the header
 * (title, thumbnail base, source type). Separate from `useAutoSelect`
 * so the page can show the video context even if the auto-select call
 * hasn't been made yet.
 *
 * Uses `page_size=1` — we only need the top-level video fields
 * (video_title, source_type); scene thumbnails for clips come from
 * `AutoClipResponse` scene_ids and `SceneThumbnail` component.
 */
export function useVideoMeta(videoId: string, getToken: TokenGetter): State {
  const [state, setState] = useState<State>({
    meta: null,
    isLoading: Boolean(videoId),
    error: null,
  });

  useEffect(() => {
    if (!videoId) {
      setState({ meta: null, isLoading: false, error: null });
      return;
    }

    let cancelled = false;
    setState({ meta: null, isLoading: true, error: null });

    getVideoScenes(videoId, 1, 0, getToken)
      .then((res) => {
        if (cancelled) return;
        setState({ meta: res, isLoading: false, error: null });
      })
      .catch((err) => {
        if (cancelled) return;
        const error = err instanceof Error ? err : new Error(String(err));
        setState({ meta: null, isLoading: false, error });
      });

    return () => {
      cancelled = true;
    };
  }, [videoId, getToken]);

  return state;
}
