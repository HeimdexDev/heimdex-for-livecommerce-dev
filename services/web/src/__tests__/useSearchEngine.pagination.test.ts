/**
 * useSearchEngine pagination flow — metadata mode must send offset to
 * the backend, other modes must not; handlePageChange re-fetches;
 * new query resets page to 1; mode change resets page to 1.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";

import type { SceneSearchResponse, VideoSearchResponse } from "@/lib/types";
import { searchScenes } from "@/lib/api/search";
import { useSearchEngine, PAGE_SIZE } from "@/hooks/useSearchEngine";

vi.mock("@/lib/api/search", () => ({
  searchScenes: vi.fn(),
}));

const searchScenesMock = searchScenes as unknown as ReturnType<typeof vi.fn>;

type Mode = "metadata" | "lexical" | "semantic";

// Tests never read the internals of the stubbed response, only that
// ``searchScenes`` is called with the right body. We return an
// ``unknown``-cast shape to avoid keeping the full SceneResult literal
// in sync with schema changes.
function makeMetadataResponse(total_candidates: number): VideoSearchResponse {
  const results = Array.from(
    { length: Math.min(PAGE_SIZE, total_candidates) },
    (_, i) => ({ video_id: `vid_${i}`, video_title: `title_${i}` }),
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

function makeLexicalResponse(): SceneSearchResponse {
  return {
    results: [],
    total_candidates: 0,
    facets: { libraries: [], source_types: [], people_cluster_ids: [], content_types: [] },
    query: "q",
    alpha: 0.5,
    result_type: "scene",
  } as unknown as SceneSearchResponse;
}

function renderEngine(mode: Mode) {
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
  return renderHook(({ m }) => useSearchEngine({ ...options, searchMode: m }, deps), {
    initialProps: { m: mode },
  });
}

beforeEach(() => {
  searchScenesMock.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("useSearchEngine pagination flow", () => {
  it("initial search starts at page 1 with no offset", async () => {
    searchScenesMock.mockResolvedValue(makeMetadataResponse(142));
    const { result } = renderEngine("metadata");

    await act(async () => {
      await result.current.handleSearch("센트룸");
    });

    expect(searchScenesMock).toHaveBeenCalledTimes(1);
    const body = searchScenesMock.mock.calls[0][0];
    expect(body.q).toBe("센트룸");
    // offset is omitted (or 0) on the initial page.
    expect(body.offset ?? 0).toBe(0);
    expect(result.current.currentPage).toBe(1);
  });

  it("handlePageChange(3) re-fetches with offset=40 in metadata mode", async () => {
    searchScenesMock.mockResolvedValue(makeMetadataResponse(142));
    const { result } = renderEngine("metadata");

    await act(async () => {
      await result.current.handleSearch("센트룸");
    });
    searchScenesMock.mockClear();
    searchScenesMock.mockResolvedValue(makeMetadataResponse(142));

    await act(async () => {
      await result.current.handlePageChange(3);
    });

    expect(searchScenesMock).toHaveBeenCalledTimes(1);
    const body = searchScenesMock.mock.calls[0][0];
    expect(body.offset).toBe(2 * PAGE_SIZE);
    expect(result.current.currentPage).toBe(3);
  });

  it("totalPages uses total_candidates for metadata, not results.length", async () => {
    searchScenesMock.mockResolvedValue(makeMetadataResponse(142));
    const { result } = renderEngine("metadata");

    await act(async () => {
      await result.current.handleSearch("센트룸");
    });

    // 142 total with PAGE_SIZE=20 → 8 pages (ceil(142/20))
    await waitFor(() => {
      expect(result.current.totalPages).toBe(Math.ceil(142 / PAGE_SIZE));
    });
  });

  it("handlePageChange does NOT send offset for lexical mode", async () => {
    searchScenesMock.mockResolvedValue(makeLexicalResponse());
    const { result } = renderEngine("lexical");

    await act(async () => {
      await result.current.handleSearch("q");
    });
    searchScenesMock.mockClear();

    await act(async () => {
      await result.current.handlePageChange(3);
    });

    // Lexical mode doesn't re-fetch; currentPage moved client-side only.
    expect(searchScenesMock).not.toHaveBeenCalled();
    expect(result.current.currentPage).toBe(3);
  });

  it("new query resets page back to 1", async () => {
    searchScenesMock.mockResolvedValue(makeMetadataResponse(142));
    const { result } = renderEngine("metadata");

    await act(async () => {
      await result.current.handleSearch("센트룸");
    });
    await act(async () => {
      await result.current.handlePageChange(5);
    });
    expect(result.current.currentPage).toBe(5);

    searchScenesMock.mockResolvedValue(makeMetadataResponse(30));
    await act(async () => {
      await result.current.handleSearch("하림");
    });

    expect(result.current.currentPage).toBe(1);
    const lastCall = searchScenesMock.mock.calls.at(-1)?.[0];
    expect(lastCall?.offset ?? 0).toBe(0);
    expect(lastCall?.q).toBe("하림");
  });

  it("switching search mode resets page to 1", async () => {
    searchScenesMock.mockResolvedValue(makeMetadataResponse(142));
    const { result, rerender } = renderEngine("metadata");

    await act(async () => {
      await result.current.handleSearch("센트룸");
    });
    await act(async () => {
      await result.current.handlePageChange(4);
    });
    expect(result.current.currentPage).toBe(4);

    rerender({ m: "lexical" });

    await waitFor(() => {
      expect(result.current.currentPage).toBe(1);
    });
  });
});
