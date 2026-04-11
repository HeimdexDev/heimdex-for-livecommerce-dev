import { useState, useCallback, useRef } from "react";
import { searchScenes } from "@/lib/api/search";
import type { SceneResult } from "@/lib/types";

type TokenGetter = () => Promise<string | null>;

const MAX_RESULTS = 10;

export function useRowSearch(getToken: TokenGetter) {
  const [results, setResults] = useState<SceneResult[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const search = useCallback(
    async (query: string) => {
      if (!query.trim()) return;

      // Cancel previous request
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setIsLoading(true);
      setError(null);

      try {
        const response = await searchScenes(
          {
            q: query,
            alpha: 0.5,
            filters: { content_types: ["video"] },
            group_by: "scene",
          },
          getToken,
        );

        if (controller.signal.aborted) return;

        setResults(response.results.slice(0, MAX_RESULTS));
      } catch (err) {
        if (controller.signal.aborted) return;
        setError(
          err instanceof Error ? err.message : "검색 중 오류가 발생했습니다",
        );
        setResults([]);
      } finally {
        if (!controller.signal.aborted) {
          setIsLoading(false);
        }
      }
    },
    [getToken],
  );

  const clear = useCallback(() => {
    abortRef.current?.abort();
    setResults([]);
    setError(null);
    setIsLoading(false);
  }, []);

  return { results, isLoading, error, search, clear };
}
