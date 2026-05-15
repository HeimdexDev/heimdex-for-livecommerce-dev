"use client";

import { useState, useEffect, useCallback } from "react";
import { useAuth } from "@/lib/auth";
import { getVideos, getVideoScenes, getVideoStats } from "@/lib/api/videos";
import type {
  VideoSummary,
  VideoScene,
  VideoStats,
  VideoFilters,
  VideoFacets,
} from "@/lib/types";
import { ApiError } from "@/lib/types";

export interface UseVideosReturn {
  videos: VideoSummary[];
  stats: VideoStats | null;
  facets: VideoFacets | null;
  filters: VideoFilters;
  isLoading: boolean;
  isLoadingMore: boolean;
  isLoadingScenes: boolean;
  error: string | null;
  nextCursor: string | null;
  total: number;

  selectedVideoId: string | null;
  selectedVideoScenes: VideoScene[];
  selectedVideoTotal: number;

  setFilters: (filters: VideoFilters) => void;
  loadMore: () => Promise<void>;
  selectVideo: (videoId: string) => Promise<void>;
  closeDrawer: () => void;
  refresh: () => Promise<void>;
}

export function useVideos(): UseVideosReturn {
  const { getAccessToken } = useAuth();

  const [videos, setVideos] = useState<VideoSummary[]>([]);
  const [stats, setStats] = useState<VideoStats | null>(null);
  const [facets, setFacets] = useState<VideoFacets | null>(null);
  const [filters, setFiltersState] = useState<VideoFilters>({ sort: "latest", page_size: 20 });
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [isLoadingScenes, setIsLoadingScenes] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [total, setTotal] = useState(0);

  const [selectedVideoId, setSelectedVideoId] = useState<string | null>(null);
  const [selectedVideoScenes, setSelectedVideoScenes] = useState<VideoScene[]>([]);
  const [selectedVideoTotal, setSelectedVideoTotal] = useState(0);

  const fetchVideos = useCallback(
    async (currentFilters: VideoFilters, append = false) => {
      if (!append) setIsLoading(true);
      else setIsLoadingMore(true);
      setError(null);

      try {
        const response = await getVideos(currentFilters, getAccessToken);
        if (append) {
          setVideos((prev) => [...prev, ...response.videos]);
        } else {
          setVideos(response.videos);
        }
        setTotal(response.total);
        setNextCursor(response.next_cursor);
        setFacets(response.facets);
      } catch (err) {
        const msg = err instanceof ApiError ? err.detail : "Failed to load videos";
        setError(msg);
      } finally {
        setIsLoading(false);
        setIsLoadingMore(false);
      }
    },
    [getAccessToken],
  );

  const fetchStats = useCallback(async () => {
    try {
      const result = await getVideoStats(getAccessToken);
      setStats(result);
    } catch {
      // Stats are non-critical; don't block UI
    }
  }, [getAccessToken]);

  useEffect(() => {
    fetchVideos(filters);
    fetchStats();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const setFilters = useCallback(
    (newFilters: VideoFilters) => {
      const updated = { ...newFilters, after: undefined };
      setFiltersState(updated);
      fetchVideos(updated);
    },
    [fetchVideos],
  );

  const loadMore = useCallback(async () => {
    if (!nextCursor || isLoadingMore) return;
    const withCursor = { ...filters, after: nextCursor };
    await fetchVideos(withCursor, true);
  }, [nextCursor, isLoadingMore, filters, fetchVideos]);

  const selectVideo = useCallback(
    async (videoId: string) => {
      setSelectedVideoId(videoId);
      setIsLoadingScenes(true);
      setSelectedVideoScenes([]);
      setSelectedVideoTotal(0);

      try {
        const response = await getVideoScenes(videoId, 50, 0, getAccessToken);
        setSelectedVideoScenes(response.scenes);
        setSelectedVideoTotal(response.total);
      } catch (err) {
        const msg = err instanceof ApiError ? err.detail : "Failed to load scenes";
        setError(msg);
      } finally {
        setIsLoadingScenes(false);
      }
    },
    [getAccessToken],
  );

  const closeDrawer = useCallback(() => {
    setSelectedVideoId(null);
    setSelectedVideoScenes([]);
    setSelectedVideoTotal(0);
  }, []);

  const refresh = useCallback(async () => {
    const resetFilters = { ...filters, after: undefined };
    await Promise.all([fetchVideos(resetFilters), fetchStats()]);
  }, [filters, fetchVideos, fetchStats]);

  return {
    videos,
    stats,
    facets,
    filters,
    isLoading,
    isLoadingMore,
    isLoadingScenes,
    error,
    nextCursor,
    total,
    selectedVideoId,
    selectedVideoScenes,
    selectedVideoTotal,
    setFilters,
    loadMore,
    selectVideo,
    closeDrawer,
    refresh,
  };
}
