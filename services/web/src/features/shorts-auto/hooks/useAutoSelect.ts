"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { postAutoSelect } from "@/lib/api/shorts-auto";
import type { AutoSelectRequest, AutoSelectResponse } from "@/lib/types";

type TokenGetter = () => Promise<string | null>;

interface MutationState {
  data: AutoSelectResponse | null;
  error: Error | null;
  isLoading: boolean;
}

const INITIAL: MutationState = { data: null, error: null, isLoading: false };

/**
 * Mutation hook for POST /api/shorts/auto-select.
 *
 * Returns a stable object (wrapped in useMemo) so callers' useCallback
 * deps that include this result don't churn on every render.
 * Unmount-safe: setState no-ops after the component is torn down.
 */
export function useAutoSelect(getToken: TokenGetter) {
  const [state, setState] = useState<MutationState>(INITIAL);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const mutate = useCallback(
    async (body: AutoSelectRequest): Promise<AutoSelectResponse | null> => {
      if (mountedRef.current) {
        setState({ data: null, error: null, isLoading: true });
      }
      try {
        const data = await postAutoSelect(body, getToken);
        if (mountedRef.current) {
          setState({ data, error: null, isLoading: false });
        }
        return data;
      } catch (err) {
        const error = err instanceof Error ? err : new Error(String(err));
        if (mountedRef.current) {
          setState({ data: null, error, isLoading: false });
        }
        return null;
      }
    },
    [getToken],
  );

  const reset = useCallback(() => {
    if (mountedRef.current) setState(INITIAL);
  }, []);

  return useMemo(
    () => ({ ...state, mutate, reset }),
    [state, mutate, reset],
  );
}
