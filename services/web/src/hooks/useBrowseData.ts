import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import { getVideos, getVideoStats } from "@/lib/api/videos";
import { getSnapshot, setData } from "@/lib/back-nav-cache";
import type { VideoSummary, VideoStats } from "@/lib/types";

function formatDateKr(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

type BrowseSortBy = "latest" | "alpha_asc" | "alpha_desc";
type SourceType = "gdrive" | "removable_disk" | "local" | "youtube";

export interface UseBrowseDataOptions {
  contentTypes?: ("video" | "image")[];
  sourceTypes?: SourceType[];
  dateStart: Date | null;
  dateEnd: Date | null;
  sortBy: BrowseSortBy;
  enabled: boolean; // false when in search mode
  getAccessToken: () => Promise<string | null>;
  /**
   * When set, accumulated browse pages are restored on mount if the
   * current filter combo matches the cached snapshot. Pair with
   * `useBackNavScroll` (same key) to also restore scroll position.
   * The caller passes the same key here and to that hook.
   */
  cacheKey?: string;
}

interface BrowseSnapshot {
  videos: VideoSummary[];
  totalVideos: number;
  nextCursor: string | null;
}

export const BROWSE_CACHE_NAMESPACE = "browse-data";

/**
 * Build a stable cache key from the inputs that determine which
 * page-1 response the server would return. Must match the inputs
 * that `useBrowseData` itself uses to refetch — otherwise the cache
 * could hand back a snapshot that doesn't match the active filters.
 */
export function buildBrowseCacheKey(input: {
  contentTypes?: ("video" | "image")[];
  sourceTypes?: SourceType[];
  dateStart: Date | null;
  dateEnd: Date | null;
  sortBy: BrowseSortBy;
}): string {
  return JSON.stringify({
    c: input.contentTypes ? [...input.contentTypes].sort() : null,
    s: input.sourceTypes ? [...input.sourceTypes].sort() : null,
    ds: input.dateStart ? formatDateKr(input.dateStart) : null,
    de: input.dateEnd ? formatDateKr(input.dateEnd) : null,
    o: input.sortBy,
  });
}

export interface UseBrowseDataReturn {
  videos: VideoSummary[];
  totalVideos: number;
  stats: VideoStats | null;
  isLoading: boolean;
  isLoadingMore: boolean;
  loadMore: () => Promise<void>;
  hasMore: boolean;
  refetch: () => Promise<void>;
}

export function useBrowseData({
  contentTypes,
  sourceTypes,
  dateStart,
  dateEnd,
  sortBy,
  enabled,
  getAccessToken,
  cacheKey,
}: UseBrowseDataOptions): UseBrowseDataReturn {
  // Snapshot lookup happens once at mount under whatever key was first
  // supplied; subsequent key changes are treated as filter changes
  // (existing useEffect refetch path) so the cache is intentionally
  // not consulted again.
  const initialSnapshot = useMemo(() => {
    if (!cacheKey) return null;
    const snap = getSnapshot<BrowseSnapshot>(BROWSE_CACHE_NAMESPACE, cacheKey);
    return snap?.data ?? null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const hydratedFromCacheRef = useRef<boolean>(initialSnapshot !== null);

  const [videos, setVideos] = useState<VideoSummary[]>(
    () => initialSnapshot?.videos ?? [],
  );
  const [totalVideos, setTotalVideos] = useState(
    () => initialSnapshot?.totalVideos ?? 0,
  );
  const [stats, setStats] = useState<VideoStats | null>(null);
  const [isLoading, setIsLoading] = useState(initialSnapshot === null);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(
    () => initialSnapshot?.nextCursor ?? null,
  );

  const fetchData = useCallback(async () => {
    setIsLoading(true);
    setNextCursor(null);
    try {
      const tokenGetter = () => getAccessToken();
      const [videosRes, statsRes] = await Promise.all([
        getVideos(
          {
            sort: sortBy,
            page_size: 20,
            content_types: contentTypes,
            source_types: sourceTypes,
            date_from: dateStart ? formatDateKr(dateStart) : undefined,
            date_to: dateEnd ? formatDateKr(dateEnd) : undefined,
          },
          tokenGetter,
        ),
        getVideoStats(tokenGetter),
      ]);
      setVideos(videosRes.videos);
      setTotalVideos(videosRes.total);
      setNextCursor(videosRes.next_cursor);
      setStats(statsRes);
    } catch {
      setVideos([]);
      setTotalVideos(0);
      setNextCursor(null);
    } finally {
      setIsLoading(false);
    }
  }, [getAccessToken, sortBy, contentTypes, sourceTypes, dateStart, dateEnd]);

  const loadMore = useCallback(async () => {
    if (!nextCursor || isLoadingMore) return;
    setIsLoadingMore(true);
    try {
      const tokenGetter = () => getAccessToken();
      const videosRes = await getVideos(
        {
          sort: sortBy,
          page_size: 20,
          content_types: contentTypes,
          source_types: sourceTypes,
          date_from: dateStart ? formatDateKr(dateStart) : undefined,
          date_to: dateEnd ? formatDateKr(dateEnd) : undefined,
          after: nextCursor,
        },
        tokenGetter,
      );
      setVideos((prev) => [...prev, ...videosRes.videos]);
      setTotalVideos(videosRes.total);
      setNextCursor(videosRes.next_cursor);
    } catch {
      // Keep existing videos, just stop loading more
    } finally {
      setIsLoadingMore(false);
    }
  }, [getAccessToken, nextCursor, isLoadingMore, sortBy, contentTypes, sourceTypes, dateStart, dateEnd]);

  useEffect(() => {
    if (!enabled) return;
    // Hydrated state covers the first render only. Any later filter
    // change recreates `fetchData` (its closure depends on the filter
    // inputs), which fires this effect again — at that point we want
    // a real refetch.
    if (hydratedFromCacheRef.current) {
      hydratedFromCacheRef.current = false;
      return;
    }
    fetchData();
  }, [fetchData, enabled]);

  // Persist the latest browse state under the active cacheKey. Skipped
  // while loading to avoid caching transient empty arrays during a
  // refetch.
  useEffect(() => {
    if (!cacheKey || !enabled) return;
    if (isLoading || isLoadingMore) return;
    setData<BrowseSnapshot>(BROWSE_CACHE_NAMESPACE, cacheKey, {
      videos,
      totalVideos,
      nextCursor,
    });
  }, [cacheKey, enabled, isLoading, isLoadingMore, videos, totalVideos, nextCursor]);

  return {
    videos,
    totalVideos,
    stats,
    isLoading,
    isLoadingMore,
    loadMore,
    hasMore: nextCursor !== null,
    refetch: fetchData,
  };
}
