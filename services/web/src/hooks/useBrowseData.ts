import { useState, useCallback, useEffect } from "react";
import { getVideos, getVideoStats } from "@/lib/api/videos";
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
}: UseBrowseDataOptions): UseBrowseDataReturn {
  const [videos, setVideos] = useState<VideoSummary[]>([]);
  const [totalVideos, setTotalVideos] = useState(0);
  const [stats, setStats] = useState<VideoStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);

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
    if (enabled) {
      fetchData();
    }
  }, [fetchData, enabled]);

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
