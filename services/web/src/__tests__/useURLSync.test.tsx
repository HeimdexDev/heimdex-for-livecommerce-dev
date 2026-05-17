import { renderHook } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock next/navigation — must be hoisted before imports that use it
const mockReplace = vi.fn();
let mockPathname = "/";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
  usePathname: () => mockPathname,
}));

// Import after mocks
import { useURLSync } from "@/hooks/useURLSync";
import type { DashboardSearchState } from "@/lib/search-state";

// Helper to create a default state
function makeState(
  overrides?: Partial<DashboardSearchState>,
): DashboardSearchState {
  return {
    query: "",
    searchMode: "lexical",
    groupBy: "scene",
    sortBy: "latest",
    contentType: "all",
    referenceMode: false,
    currentPage: 1,
    sourceFilters: new Set(["gdrive", "removable_disk", "local", "youtube"] as const),
    dateStart: null,
    dateEnd: null,
    ...overrides,
  };
}

describe("useURLSync", () => {
  beforeEach(() => {
    mockReplace.mockClear();
    mockPathname = "/";
  });

  it("skips URL sync on initial render", () => {
    renderHook(() => useURLSync(makeState()));
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it("syncs to current pathname (not hardcoded /)", () => {
    mockPathname = "/images";
    const { rerender } = renderHook(
      ({ state }) => useURLSync(state),
      { initialProps: { state: makeState() } },
    );
    // Trigger re-render with changed state
    rerender({ state: makeState({ query: "test" }) });
    expect(mockReplace).toHaveBeenCalledWith(
      expect.stringContaining("/images?"),
      expect.anything(),
    );
    expect(mockReplace).not.toHaveBeenCalledWith(
      expect.stringContaining("/?"),
      expect.anything(),
    );
  });

  it("stays on / when rendered on home page", () => {
    mockPathname = "/";
    const { rerender } = renderHook(
      ({ state }) => useURLSync(state),
      { initialProps: { state: makeState() } },
    );
    rerender({ state: makeState({ query: "hello" }) });
    expect(mockReplace).toHaveBeenCalledWith(
      expect.stringMatching(/^\/\?/),
      expect.anything(),
    );
  });

  it("excludes content type from URL when lockedContentType is set", () => {
    mockPathname = "/images";
    const { rerender } = renderHook(
      ({ state }) =>
        useURLSync(state, { lockedContentType: "image" }),
      {
        initialProps: {
          state: makeState({ contentType: "image", query: "test" }),
        },
      },
    );
    rerender({ state: makeState({ contentType: "image", query: "search" }) });
    const url = mockReplace.mock.calls[0]?.[0] as string;
    expect(url).not.toContain("type=image");
  });

  it("uses bare pathname when no params differ from defaults", () => {
    mockPathname = "/images";
    const { rerender } = renderHook(
      ({ state }) =>
        useURLSync(state, { lockedContentType: "image" }),
      {
        initialProps: { state: makeState({ contentType: "image" }) },
      },
    );
    // Change sortBy away from default — URL should have params
    rerender({ state: makeState({ contentType: "image", sortBy: "alpha_asc" }) });
    const urlWithParams = mockReplace.mock.calls[0]?.[0] as string;
    expect(urlWithParams).toContain("sort=alpha_asc");

    mockReplace.mockClear();

    // Back to defaults (with locked content type) — URL should be bare pathname
    rerender({ state: makeState({ contentType: "image" }) });
    const urlBare = mockReplace.mock.calls[0]?.[0] as string;
    expect(urlBare).toBe("/images");
  });
});
