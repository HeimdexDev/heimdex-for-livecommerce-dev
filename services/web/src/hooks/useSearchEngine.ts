import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import { searchScenes, SearchRateLimitError } from "@/lib/api/search";
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
export const PAGE_SIZE = 20;
// Moodboard diversification cap — raised from the default of 4 to keep
// 60-item pages from requiring too many distinct videos.
const MOODBOARD_MAX_PER_VIDEO = 6;

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
  /** Color family for dominant-color search (e.g. 'pink') */
  colorFamily?: string;
  /**
   * Override result count (default: PAGE_SIZE=20). When set, sent as
   * `page_size` on the search request and used for client-side slicing.
   * Used by the image/moodboard surface to show more results at once.
   */
  pageSize?: number;
}

export interface UseSearchEngineReturn {
  searchResponse: AnySearchResponse | null;
  isSearchMode: boolean;
  activeQuery: string;
  performSearch: (query: string, isRefMode?: boolean) => Promise<void>;
  performColorSearch: () => Promise<void>;
  handleSearch: (query: string) => Promise<void>;
  clearSearch: () => void;
  sortedResults: (SceneResult | VideoResult)[];
  paginatedResults: (SceneResult | VideoResult)[];
  currentPage: number;
  totalPages: number;
  setCurrentPage: (page: number) => void;
  /**
   * Change to a specific page. For metadata mode this triggers a
   * backend re-fetch with ``offset=(page-1)*page_size`` and replaces
   * ``searchResponse`` with the new page's results. For other modes
   * it just moves the client-side slice within the already-returned
   * candidate list.
   */
  handlePageChange: (page: number) => Promise<void>;
  /**
   * Epoch ms when the most recent search/pagination request was
   * rejected with 429. ``null`` when no recent rate-limit event. UI
   * components compute whether the banner should still render via
   * ``Date.now() - rateLimitedAt < rateLimitRetryAfter * 1000``.
   */
  rateLimitedAt: number | null;
  /** Seconds (from the backend's ``Retry-After`` header) the client
   *  should wait before its next request lands. */
  rateLimitRetryAfter: number;
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
    colorFamily,
    pageSize,
  } = options;

  const effectivePageSize = pageSize ?? PAGE_SIZE;
  const isMoodboardSize = pageSize !== undefined && pageSize > PAGE_SIZE;

  const { setIsLoading, setSortBy } = deps;

  const [searchResponse, setSearchResponse] = useState<AnySearchResponse | null>(null);
  const [activeQuery, setActiveQuery] = useState(initialQuery ?? "");
  const [currentPage, setCurrentPage] = useState(1);
  // Rate-limit surface state — populated on 429, consumed by the UI to
  // render a transient banner. Keeps ``searchResponse`` untouched so
  // the previously-rendered results stay visible through the throttle.
  const [rateLimitedAt, setRateLimitedAt] = useState<number | null>(null);
  const [rateLimitRetryAfter, setRateLimitRetryAfter] = useState<number>(60);
  const sortBeforeSearchRef = useRef<SortOption>(sortBy);

  // Guard against races when the user clicks pages faster than the
  // backend responds. Only the latest request's response is accepted;
  // older in-flight calls get dropped on arrival.
  const requestIdRef = useRef(0);

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
  // Metadata-mode responses are pre-paginated server-side — backend
  // returns exactly one page per offset, so we render sortedResults
  // directly. Other modes still rely on client-side slicing over the
  // over-fetched candidate list.
  const isMetadataVideoResponse =
    searchResponse?.result_type === "video" && searchMode === "metadata";
  const paginatedResults = useMemo(() => {
    if (!sortedResults.length) return [];
    if (isMetadataVideoResponse) return sortedResults;
    const start = (currentPage - 1) * effectivePageSize;
    return sortedResults.slice(start, start + effectivePageSize);
  }, [sortedResults, currentPage, effectivePageSize, isMetadataVideoResponse]);

  const searchTotalPages = useMemo(() => {
    if (!isSearchMode || !searchResponse) return 1;
    if (isMetadataVideoResponse) {
      // Server supplies the true distinct-video cardinality — never
      // trust sortedResults.length here (it's capped at page_size).
      return Math.max(
        1,
        Math.ceil(searchResponse.total_candidates / effectivePageSize),
      );
    }
    return Math.max(1, Math.ceil(sortedResults.length / effectivePageSize));
  }, [isSearchMode, searchResponse, isMetadataVideoResponse, sortedResults.length, effectivePageSize]);
  const totalPages = searchTotalPages;

  // ── Reset pagination on sort change ─────────────────────────────────────
  useEffect(() => {
    setCurrentPage(1);
  }, [sortBy]);

  // ── Reset pagination when the search mode changes ───────────────────────
  // Stale `currentPage=5` from a prior metadata search would send a
  // meaningless `offset=80` to lexical/semantic, which the backend
  // ignores — but the page number would still render wrong. Reset.
  useEffect(() => {
    setCurrentPage(1);
  }, [searchMode]);

  // ── Auto-dismiss the rate-limit banner after Retry-After seconds ────────
  // Keeps DashboardContent free of banner bookkeeping; the hook owns the
  // transient state + its lifetime.
  useEffect(() => {
    if (rateLimitedAt == null) return;
    const handle = setTimeout(
      () => setRateLimitedAt(null),
      rateLimitRetryAfter * 1000,
    );
    return () => clearTimeout(handle);
  }, [rateLimitedAt, rateLimitRetryAfter]);

  // ── Core search ─────────────────────────────────────────────────────────
  const performSearch = useCallback(
    async (
      q: string,
      isRefMode: boolean = referenceMode,
      opts?: { offsetOverride?: number; resetPage?: boolean },
    ) => {
      const offsetOverride = opts?.offsetOverride ?? 0;
      const shouldResetPage = opts?.resetPage ?? true;
      setIsLoading(true);
      if (shouldResetPage) setCurrentPage(1);
      const thisRequestId = ++requestIdRef.current;
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
          {
            q,
            alpha: 0.5,
            filters,
            group_by: groupBy,
            search_mode: searchMode,
            color_family: colorFamily,
            // Offset is metadata-only on the backend. Sending from
            // other modes is harmless (backend logs + ignores) but
            // wastes bytes, so only include when non-zero.
            ...(offsetOverride > 0 && searchMode === "metadata"
              ? { offset: offsetOverride }
              : {}),
            ...(isMoodboardSize
              ? { page_size: effectivePageSize, max_per_video: MOODBOARD_MAX_PER_VIDEO }
              : {}),
          },
          tokenGetter,
        );
        if (thisRequestId !== requestIdRef.current) return;
        setSearchResponse(res);
        setActiveQuery(q);
      } catch (err) {
        if (thisRequestId !== requestIdRef.current) return;
        if (err instanceof SearchRateLimitError) {
          // Preserve previous results + surface the event to the UI.
          // The user sees their old page still rendered AND a banner
          // explaining why the new request didn't land.
          setRateLimitedAt(Date.now());
          setRateLimitRetryAfter(err.retryAfterSeconds);
          return;
        }
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
        if (thisRequestId === requestIdRef.current) setIsLoading(false);
      }
    },
    [getAccessToken, groupBy, searchMode, contentTypes, sourceFilters, dateStart, dateEnd, referenceMode, setIsLoading, colorFamily, isMoodboardSize, effectivePageSize],
  );

  // ── Page change — metadata mode re-fetches, others just move the slice ──
  const handlePageChange = useCallback(
    async (nextPage: number) => {
      if (nextPage === currentPage) return;
      setCurrentPage(nextPage);
      if (!activeQuery) return;
      if (searchMode !== "metadata") return;  // lexical/semantic: no re-fetch
      await performSearch(activeQuery, referenceMode, {
        offsetOverride: (nextPage - 1) * effectivePageSize,
        resetPage: false,
      });
    },
    [currentPage, activeQuery, searchMode, referenceMode, effectivePageSize, performSearch],
  );

  // ── handleSearch — takes a raw query string (slash commands parsed in component) ──
  // resetPage=true by default inside performSearch, so a fresh query
  // always starts at page 1 regardless of prior pagination state.
  const handleSearch = useCallback(
    async (query: string) => {
      if (!query.trim()) return;
      if (!isSearchMode) {
        sortBeforeSearchRef.current = sortBy;
      }
      await performSearch(query, referenceMode);
    },
    [performSearch, isSearchMode, sortBy, referenceMode, setSortBy],
  );

  // ── Color-only search — dedicated path, no text query needed ─────────────
  const performColorSearch = useCallback(
    async () => {
      if (!colorFamily) return;
      setIsLoading(true);
      setCurrentPage(1);
      try {
        const tokenGetter = () => getAccessToken();
        const filters: SearchFilters = {};

        if (contentTypes.length === 1 && contentTypes[0] === "video") {
          filters.content_types = ["video"];
        } else if (contentTypes.length === 1 && contentTypes[0] === "image") {
          filters.content_types = ["image"];
        } else {
          filters.content_types = ["video", "image"];
        }

        if (sourceFilters.size !== ALL_SOURCES.length) {
          filters.source_types = Array.from(sourceFilters);
        }

        if (dateStart) filters.date_from = formatDateKr(dateStart);
        if (dateEnd) filters.date_to = formatDateKr(dateEnd);

        const res = await searchScenes(
          {
            q: "",
            alpha: 0.5,
            filters,
            group_by: groupBy,
            search_mode: "semantic",
            color_family: colorFamily,
            ...(isMoodboardSize
              ? { page_size: effectivePageSize, max_per_video: MOODBOARD_MAX_PER_VIDEO }
              : {}),
          },
          tokenGetter,
        );
        setSearchResponse(res);
        setActiveQuery("");
      } catch (err) {
        if (err instanceof SearchRateLimitError) {
          // Preserve previous results; surface the event to the UI
          // (same rationale as performSearch's catch).
          setRateLimitedAt(Date.now());
          setRateLimitRetryAfter(err.retryAfterSeconds);
          return;
        }
        const emptyResponse: SceneSearchResponse = {
          results: [],
          total_candidates: 0,
          facets: { libraries: [], source_types: [], people_cluster_ids: [], content_types: [] },
          query: "",
          alpha: 0.5,
          result_type: "scene",
        };
        setSearchResponse(emptyResponse);
      } finally {
        setIsLoading(false);
      }
    },
    [getAccessToken, groupBy, contentTypes, sourceFilters, dateStart, dateEnd, colorFamily, setIsLoading, isMoodboardSize, effectivePageSize],
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
    } else if (colorFamily) {
      performColorSearch();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groupBy, searchMode, contentTypes, sourceFilters, dateStart, dateEnd, colorFamily]);

  return {
    searchResponse,
    isSearchMode,
    activeQuery,
    performSearch,
    performColorSearch,
    handleSearch,
    clearSearch,
    sortedResults,
    paginatedResults,
    currentPage,
    totalPages,
    setCurrentPage,
    handlePageChange,
    rateLimitedAt,
    rateLimitRetryAfter,
    sortBeforeSearch: sortBeforeSearchRef.current,
  };
}
