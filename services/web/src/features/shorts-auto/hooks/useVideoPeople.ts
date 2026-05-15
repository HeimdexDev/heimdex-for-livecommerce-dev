"use client";

import { useEffect, useState } from "react";

import { getVideoPeople } from "@/lib/api/videos";
import type { PersonResponse } from "@/lib/types";

type TokenGetter = () => Promise<string | null>;

interface State {
  people: PersonResponse[];
  isLoading: boolean;
  error: Error | null;
}

const INITIAL: State = { people: [], isLoading: false, error: null };

/**
 * Lazy-load the people who appear in a specific video.
 *
 * Wraps the existing ``GET /api/videos/{video_id}/people`` endpoint
 * (see ``services/api/app/modules/videos/router.py:167``). Used by the
 * auto-shorts inline person picker so users only see clusters that
 * actually appear in the video being shorts-ified, not the whole org.
 *
 * Empty ``videoId`` short-circuits to an idle state — the picker is
 * blocking but mounts before the parent has resolved its videoId
 * query param.
 */
export function useVideoPeople(videoId: string, getToken: TokenGetter): State {
  const [state, setState] = useState<State>(INITIAL);

  useEffect(() => {
    if (!videoId) {
      setState(INITIAL);
      return;
    }

    let cancelled = false;
    setState({ people: [], isLoading: true, error: null });

    getVideoPeople(videoId, getToken)
      .then((res) => {
        if (cancelled) return;
        setState({ people: res.people ?? [], isLoading: false, error: null });
      })
      .catch((err) => {
        if (cancelled) return;
        const error = err instanceof Error ? err : new Error(String(err));
        setState({ people: [], isLoading: false, error });
      });

    return () => {
      cancelled = true;
    };
  }, [videoId, getToken]);

  return state;
}
