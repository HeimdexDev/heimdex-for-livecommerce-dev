import { renderHook, act, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

const { mockGetVideos, mockGetVideoStats } = vi.hoisted(() => ({
  mockGetVideos: vi.fn(),
  mockGetVideoStats: vi.fn(),
}));

vi.mock("@/lib/api/videos", () => ({
  getVideos: mockGetVideos,
  getVideoStats: mockGetVideoStats,
}));

import {
  useBrowseData,
  buildBrowseCacheKey,
  BROWSE_CACHE_NAMESPACE,
} from "@/hooks/useBrowseData";
import { _resetAllSnapshots, getSnapshot } from "@/lib/back-nav-cache";

// Stable references shared across renders — useBrowseData's fetchData
// memo-keys on these arrays, so a fresh array per render would re-fire
// the fetch effect on every render and never settle.
const STABLE_CONTENT_TYPES: ("video" | "image")[] = ["video"];
const STABLE_GET_TOKEN = async () => "tok";

const baseInputs = {
  contentTypes: STABLE_CONTENT_TYPES,
  sourceTypes: undefined,
  dateStart: null,
  dateEnd: null,
  sortBy: "latest" as const,
};

function makeOptions(cacheKey?: string) {
  return {
    contentTypes: baseInputs.contentTypes,
    sourceTypes: baseInputs.sourceTypes,
    dateStart: baseInputs.dateStart,
    dateEnd: baseInputs.dateEnd,
    sortBy: baseInputs.sortBy,
    enabled: true,
    getAccessToken: STABLE_GET_TOKEN,
    cacheKey,
  };
}

describe("useBrowseData cache hydration", () => {
  beforeEach(() => {
    _resetAllSnapshots();
    mockGetVideos.mockReset();
    mockGetVideoStats.mockReset();
    mockGetVideos.mockResolvedValue({
      videos: [{ video_id: "fresh-1" }],
      total: 1,
      next_cursor: null,
    });
    mockGetVideoStats.mockResolvedValue({});
  });

  it("fetches when no snapshot exists", async () => {
    const key = buildBrowseCacheKey(baseInputs);
    const { result } = renderHook(() => useBrowseData(makeOptions(key)));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(mockGetVideos).toHaveBeenCalledTimes(1);
    expect(result.current.videos).toEqual([{ video_id: "fresh-1" }]);
  });

  it("hydrates from snapshot and skips initial fetch", async () => {
    const key = buildBrowseCacheKey(baseInputs);
    // Pre-seed the cache as if a previous mount had already populated it.
    const cached = {
      videos: [{ video_id: "cached-1" }, { video_id: "cached-2" }],
      totalVideos: 50,
      nextCursor: "cursor-abc",
    };
    // Use the public setData API via the cache module.
    const { setData } = await import("@/lib/back-nav-cache");
    setData(BROWSE_CACHE_NAMESPACE, key, cached);

    const { result } = renderHook(() => useBrowseData(makeOptions(key)));

    // Hydrated synchronously — no loading, no fetch.
    expect(result.current.isLoading).toBe(false);
    expect(result.current.videos).toHaveLength(2);
    expect(result.current.videos[0]?.video_id).toBe("cached-1");
    expect(result.current.totalVideos).toBe(50);
    expect(result.current.hasMore).toBe(true);
    // Allow effects to settle, then confirm no fetch.
    await act(async () => {
      await Promise.resolve();
    });
    expect(mockGetVideos).not.toHaveBeenCalled();
  });

  it("ignores snapshot when cacheKey differs from stored key", async () => {
    const oldKey = buildBrowseCacheKey({ ...baseInputs, sortBy: "alpha_asc" });
    const newKey = buildBrowseCacheKey(baseInputs);
    const { setData } = await import("@/lib/back-nav-cache");
    setData(BROWSE_CACHE_NAMESPACE, oldKey, {
      videos: [{ video_id: "stale" }],
      totalVideos: 9,
      nextCursor: null,
    });

    const { result } = renderHook(() => useBrowseData(makeOptions(newKey)));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(mockGetVideos).toHaveBeenCalledTimes(1);
    expect(result.current.videos).toEqual([{ video_id: "fresh-1" }]);
  });

  it("persists data to cache after fetch settles", async () => {
    const key = buildBrowseCacheKey(baseInputs);
    mockGetVideos.mockResolvedValue({
      videos: [{ video_id: "v1" }, { video_id: "v2" }],
      total: 2,
      next_cursor: "next",
    });
    const { result } = renderHook(() => useBrowseData(makeOptions(key)));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    const snap = getSnapshot<{
      videos: { video_id: string }[];
      totalVideos: number;
      nextCursor: string | null;
    }>(BROWSE_CACHE_NAMESPACE, key);
    expect(snap?.data?.videos).toHaveLength(2);
    expect(snap?.data?.totalVideos).toBe(2);
    expect(snap?.data?.nextCursor).toBe("next");
  });
});
