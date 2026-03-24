import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import { searchScenes } from "@/lib/api/search";
import type { GroupBy } from "@/features/search/hooks/useSearch";
import type {
  SceneResult,
  VideoResult,
  AnySearchResponse,
  SceneSearchResponse,
  SearchFilters,
  SearchMode,
} from "@/lib/types";
import type { SortOption } from "@/lib/search-state";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
export const PAGE_SIZE = 16;

type SourceType = "gdrive" | "removable_disk" | "local" | "youtube";
const ALL_SOURCES: SourceType[] = ["gdrive", "removable_disk", "local", "youtube"];

function formatDateKr(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

// ---------------------------------------------------------------------------
// Interfaces
// ---------------------------------------------------------------------------
export interface UseSearchEngineOptions {
  contentTypes: ("video" | "image")[];
  sourceTypes?: string[];
  dateStart: Date | null;
  dateEnd: Date | null;
  groupBy: GroupBy;
  searchMode: SearchMode;
  sortBy: SortOption;
  referenceMode: boolean;
  getAccessToken: () => Promise<string | null>;
  initialQuery?: string;
  hadSearchParamsOnMount?: boolean;
  /** Called when sortBy should be changed (e.g. switching to relevance on first search) */
  onSortByChange?: (sort: SortOption) => void;
  /** Called to reset currentPage externally (e.g. on sortBy change) */
  onCurrentPageChange?: (page: number) => void;
  /** Source filters as a Set for filtering */
  sourceFilters: Set<SourceType>;
}

export interface UseSearchEngineReturn {
  searchResponse: AnySearchResponse | null;
  isSearchMode: boolean;
  activeQuery: string;
  performSearch: (query: string, isRefMode?: boolean) => Promise<void>;
  handleSearch: (query: string) => Promise<void>;
  clearSearch: () => void;
  sortedResults: (SceneResult | VideoResult)[];
  paginatedResults: (SceneResult | VideoResult)[];
  currentPage: number;
  totalPages: number;
  setCurrentPage: (page: number) => void;
  /** Sort value before entering search mode (for restoring on clear) */
  sortBeforeSearch: SortOption;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------
export function useSearchEngine(
  options: UseSearchEngineOptions,
  deps: {
    setIsLoading: (v: boolean) => void;
    setSortBy: (sort: SortOption) => void;
  },
): UseSearchEngineReturn {
  const {
    contentTypes,
    dateStart,
    dateEnd,
    groupBy,
    searchMode,
    sortBy,
    referenceMode,
    getAccessToken,
    initialQuery,
    hadSearchParamsOnMount,
    sourceFilters,
  } = options;

  const { setIsLoading, setSortBy } = deps;

  const [searchResponse, setSearchResponse] = useState<AnySearchResponse | null>(null);
  const [activeQuery, setActiveQuery] = useState(initialQuery ?? "");
  const [currentPage, setCurrentPage] = useState(1);
  const sortBeforeSearchRef = useRef<SortOption>(sortBy);

  const isSearchMode = searchResponse !== null;

  // ── Sorted results ──────────────────────────────────────────────────────
  const sortedResults = useMemo(() => {
    if (!searchResponse) return [];
    if (sortBy === "relevance") return searchResponse.results as (SceneResult | VideoResult)[];
    const results = [...searchResponse.results];
    if (searchResponse.result_type === "video") {
      const items = results as VideoResult[];
      if (sortBy === "latest") {
        items.sort((a, b) => (b.best_scene.capture_time ?? "").localeCompare(a.best_scene.capture_time ?? ""));
      } else if (sortBy === "alpha_asc") {
        items.sort((a, b) => (a.video_title ?? "").localeCompare(b.video_title ?? ""));
      } else if (sortBy === "alpha_desc") {
        items.sort((a, b) => (b.video_title ?? "").localeCompare(a.video_title ?? ""));
      }
      return items as (SceneResult | VideoResult)[];
    }
    const items = results as SceneResult[];
    if (sortBy === "latest") {
      items.sort((a, b) => (b.capture_time ?? "").localeCompare(a.capture_time ?? ""));
    } else if (sortBy === "alpha_asc") {
      items.sort((a, b) => (a.video_title ?? "").localeCompare(b.video_title ?? ""));
    } else if (sortBy === "alpha_desc") {
      items.sort((a, b) => (b.video_title ?? "").localeCompare(a.video_title ?? ""));
    }
    return items as (SceneResult | VideoResult)[];
  }, [searchResponse, sortBy]);

  // ── Paginated results ───────────────────────────────────────────────────
  const paginatedResults = useMemo(() => {
    if (!sortedResults.length) return [];
    const start = (currentPage - 1) * PAGE_SIZE;
    return sortedResults.slice(start, start + PAGE_SIZE);
  }, [sortedResults, currentPage]);

  const searchTotalPages = Math.max(1, Math.ceil(sortedResults.length / PAGE_SIZE));
  const totalPages = isSearchMode ? searchTotalPages : 1;

  // ── Reset pagination on sort change ─────────────────────────────────────
  useEffect(() => {
    setCurrentPage(1);
  }, [sortBy]);

  // ── Core search ─────────────────────────────────────────────────────────
  const performSearch = useCallback(
    async (q: string, isRefMode: boolean = referenceMode) => {
      setIsLoading(true);
      setCurrentPage(1);
      try {
        const tokenGetter = () => getAccessToken();
        const filters: SearchFilters = {};

        // Content type filtering
        if (contentTypes.length === 1 && contentTypes[0] === "video") {
          filters.content_types = ["video"];
        } else if (contentTypes.length === 1 && contentTypes[0] === "image") {
          filters.content_types = ["image"];
        } else {
          filters.content_types = ["video", "image"];
        }

        // Source filtering
        if (isRefMode) {
          filters.source_types = ["youtube"];
        } else if (sourceFilters.size !== ALL_SOURCES.length) {
          filters.source_types = Array.from(sourceFilters);
        }

        if (dateStart) filters.date_from = formatDateKr(dateStart);
        if (dateEnd) filters.date_to = formatDateKr(dateEnd);

        const res = await searchScenes(
          { q, alpha: 0.5, filters, group_by: groupBy, search_mode: searchMode },
          tokenGetter,
        );
        setSearchResponse(res);
        setActiveQuery(q);
      } catch {
        const emptyResponse: SceneSearchResponse = {
          results: [],
          total_candidates: 0,
          facets: { libraries: [], source_types: [], people_cluster_ids: [], content_types: [] },
          query: q,
          alpha: 0.5,
          result_type: "scene",
        };
        setSearchResponse(emptyResponse);
        setActiveQuery(q);
      } finally {
        setIsLoading(false);
      }
    },
    [getAccessToken, groupBy, searchMode, contentTypes, sourceFilters, dateStart, dateEnd, referenceMode, setIsLoading],
  );

  // ── handleSearch — takes a raw query string (slash commands parsed in component) ──
  const handleSearch = useCallback(
    async (query: string) => {
      if (!query.trim()) return;
      if (!isSearchMode) {
        sortBeforeSearchRef.current = sortBy;
        setSortBy("relevance");
      }
      await performSearch(query, referenceMode);
    },
    [performSearch, isSearchMode, sortBy, referenceMode, setSortBy],
  );

  // ── Clear search ────────────────────────────────────────────────────────
  const clearSearch = useCallback(() => {
    setSearchResponse(null);
    setActiveQuery("");
    setCurrentPage(1);
    setSortBy(sortBeforeSearchRef.current);
  }, [setSortBy]);

  // ── Auto-search on mount if URL had a query ──────────────────────────────
  const hasTriggeredInitialSearch = useRef(false);
  useEffect(() => {
    if (hasTriggeredInitialSearch.current) return;
    if (!hadSearchParamsOnMount || !initialQuery) return;
    hasTriggeredInitialSearch.current = true;
    performSearch(initialQuery);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [performSearch]);

  // ── Auto re-search when filters change ──────────────────────────────────
  useEffect(() => {
    if (activeQuery) {
      performSearch(activeQuery);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groupBy, searchMode, contentTypes, sourceFilters, dateStart, dateEnd]);

  return {
    searchResponse,
    isSearchMode,
    activeQuery,
    performSearch,
    handleSearch,
    clearSearch,
    sortedResults,
    paginatedResults,
    currentPage,
    totalPages,
    setCurrentPage,
    sortBeforeSearch: sortBeforeSearchRef.current,
  };
}
