import { useState, useCallback } from "react";
import { getVideoSceneGroups } from "@/lib/api/videos";
import type { SceneGroupsResponse } from "@/lib/types";

type TokenGetter = () => Promise<string | null>;

export function useSceneGroups(videoId: string, getToken: TokenGetter) {
  const [data, setData] = useState<SceneGroupsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchGroups = useCallback(async (threshold?: number) => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await getVideoSceneGroups(videoId, threshold, getToken);
      setData(res);
    } catch {
      setError("그룹 데이터를 불러오지 못했습니다.");
      setData(null);
    } finally {
      setIsLoading(false);
    }
  }, [videoId, getToken]);

  const clear = useCallback(() => {
    setData(null);
    setError(null);
  }, []);

  return { data, isLoading, error, fetchGroups, clear } as const;
}
