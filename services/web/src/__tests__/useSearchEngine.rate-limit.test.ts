/**
 * useSearchEngine 429 flow — the hook must preserve prior results on
 * rate-limit, surface ``rateLimitedAt`` + ``rateLimitRetryAfter`` for
 * the banner, and auto-dismiss after Retry-After seconds.
 *
 * Architectural invariant under test: a throttled fetch must NOT wipe
 * the user's visible results. Previously 429 was silently converted
 * to an empty response, which is the exact UX bug that drove the
 * per-user migration.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";

import type { SceneSearchResponse, VideoSearchResponse } from "@/lib/types";
import { searchScenes, SearchRateLimitError } from "@/lib/api/search";
import { useSearchEngine, PAGE_SIZE } from "@/hooks/useSearchEngine";

vi.mock("@/lib/api/search", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/search")>(
    "@/lib/api/search",
  );
  return {
    ...actual,
    searchScenes: vi.fn(),
  };
});

const searchScenesMock = searchScenes as unknown as ReturnType<typeof vi.fn>;

type Mode = "metadata" | "lexical" | "semantic";

function makeMetadataResponse(total_candidates: number, label = "v"): VideoSearchResponse {
  const results = Array.from(
    { length: Math.min(PAGE_SIZE, total_candidates) },
    (_, i) => ({ video_id: `${label}_${i}`, video_title: `${label}_title_${i}` }),
  );
  return {
    results,
    total_candidates,
    facets: { libraries: [], source_types: [], people_cluster_ids: [], content_types: [] },
    query: "q",
    alpha: 0.5,
    result_type: "video",
  } as unknown as VideoSearchResponse;
}

function makeSceneResponse(): SceneSearchResponse {
  return {
    results: [],
    total_candidates: 0,
    facets: { libraries: [], source_types: [], people_cluster_ids: [], content_types: [] },
    query: "q",
    alpha: 0.5,
    result_type: "scene",
  } as unknown as SceneSearchResponse;
}

function renderEngine(mode: Mode = "metadata") {
  const options = {
    contentTypes: ["video"] as ("video" | "image")[],
    sourceTypes: undefined,
    dateStart: null,
    dateEnd: null,
    groupBy: "video" as const,
    searchMode: mode,
    sortBy: "relevance" as const,
    referenceMode: false,
    getAccessToken: async () => "tok",
    sourceFilters: new Set(["gdrive", "removable_disk", "local", "youtube"]) as Set<
      "gdrive" | "removable_disk" | "local" | "youtube"
    >,
  };
  const deps = {
    setIsLoading: vi.fn(),
    setSortBy: vi.fn(),
  };
  return renderHook(() => useSearchEngine(options, deps));
}

function renderColorEngine(colorFamily: string) {
  const options = {
    contentTypes: ["video"] as ("video" | "image")[],
    sourceTypes: undefined,
    dateStart: null,
    dateEnd: null,
    groupBy: "video" as const,
    searchMode: "semantic" as const,
    sortBy: "relevance" as const,
    referenceMode: false,
    getAccessToken: async () => "tok",
    sourceFilters: new Set(["gdrive", "removable_disk", "local", "youtube"]) as Set<
      "gdrive" | "removable_disk" | "local" | "youtube"
    >,
    colorFamily,
  };
  const deps = { setIsLoading: vi.fn(), setSortBy: vi.fn() };
  return renderHook(() => useSearchEngine(options, deps));
}

beforeEach(() => {
  searchScenesMock.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("useSearchEngine rate-limit preservation", () => {
  it("429 preserves previous searchResponse (does not blank to empty)", async () => {
    // 1st call: success → fills searchResponse
    searchScenesMock.mockResolvedValueOnce(makeMetadataResponse(42, "ok"));
    const { result } = renderEngine("metadata");

    await act(async () => {
      await result.current.handleSearch("센트룸");
    });
    const prevResponse = result.current.searchResponse;
    expect(prevResponse?.results.length).toBeGreaterThan(0);
    expect(result.current.rateLimitedAt).toBeNull();

    // 2nd call: 429
    searchScenesMock.mockRejectedValueOnce(
      new SearchRateLimitError("slow down", 42),
    );
    await act(async () => {
      await result.current.handleSearch("하림");
    });

    // Results unchanged — user's page stays rendered
    expect(result.current.searchResponse).toBe(prevResponse);
    // activeQuery also untouched — no phantom "하림" label
    expect(result.current.activeQuery).toBe("센트룸");
    // Rate-limit surface populated
    expect(result.current.rateLimitedAt).not.toBeNull();
    expect(result.current.rateLimitRetryAfter).toBe(42);
  });

  it("non-429 error still blanks results (existing fallback preserved)", async () => {
    // Regression guard: only 429 gets the preserve-previous treatment.
    // Any other error continues to fall through to the empty-response
    // fallback so stale data doesn't linger on genuine failures.
    searchScenesMock.mockResolvedValueOnce(makeMetadataResponse(42));
    const { result } = renderEngine("metadata");
    await act(async () => {
      await result.current.handleSearch("센트룸");
    });

    searchScenesMock.mockRejectedValueOnce(new Error("network down"));
    await act(async () => {
      await result.current.handleSearch("하림");
    });

    // Empty response replaced the previous one
    expect(result.current.searchResponse?.results).toEqual([]);
    expect(result.current.activeQuery).toBe("하림");
    // And the rate-limit banner did NOT fire
    expect(result.current.rateLimitedAt).toBeNull();
  });

  it("429 on handlePageChange preserves the currently-rendered page", async () => {
    // Page 1 loads successfully
    searchScenesMock.mockResolvedValueOnce(makeMetadataResponse(142, "p1"));
    const { result } = renderEngine("metadata");
    await act(async () => {
      await result.current.handleSearch("센트룸");
    });
    const firstPageResponse = result.current.searchResponse;

    // Page 3 fetch gets 429'd
    searchScenesMock.mockRejectedValueOnce(
      new SearchRateLimitError("slow", 15),
    );
    await act(async () => {
      await result.current.handlePageChange(3);
    });

    // Page 1's results still visible
    expect(result.current.searchResponse).toBe(firstPageResponse);
    expect(result.current.rateLimitedAt).not.toBeNull();
    expect(result.current.rateLimitRetryAfter).toBe(15);
  });

  it("429 on performColorSearch also preserves previous results", async () => {
    // Seed with a successful semantic search
    searchScenesMock.mockResolvedValueOnce(makeSceneResponse());
    const { result } = renderColorEngine("pink");
    await act(async () => {
      await result.current.performColorSearch();
    });
    const prev = result.current.searchResponse;

    searchScenesMock.mockRejectedValueOnce(
      new SearchRateLimitError("throttled", 30),
    );
    await act(async () => {
      await result.current.performColorSearch();
    });

    expect(result.current.searchResponse).toBe(prev);
    expect(result.current.rateLimitedAt).not.toBeNull();
    expect(result.current.rateLimitRetryAfter).toBe(30);
  });
});

describe("useSearchEngine rate-limit auto-dismiss", () => {
  it("clears rateLimitedAt after Retry-After seconds", async () => {
    // Real timers throughout — fake timers break React 18's async
    // scheduling here, and scoping fake timers to just setTimeout
    // still misses the scheduling of the effect. Keep it honest by
    // using a short (0.3s) Retry-After and waiting with waitFor.
    searchScenesMock.mockResolvedValueOnce(makeMetadataResponse(10));
    const { result } = renderEngine("metadata");
    await act(async () => {
      await result.current.handleSearch("q");
    });

    searchScenesMock.mockRejectedValueOnce(
      new SearchRateLimitError("slow", 0.3),
    );
    await act(async () => {
      await result.current.handleSearch("q2");
    });
    expect(result.current.rateLimitedAt).not.toBeNull();

    await waitFor(
      () => {
        expect(result.current.rateLimitedAt).toBeNull();
      },
      { timeout: 1500 },
    );
  });
});
