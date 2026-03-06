/**
 * Dashboard search state ↔ URL search params serialization.
 *
 * Pure functions with no React dependencies — testable in isolation.
 * Used by DashboardContent to persist filter/search state in the URL
 * so that browser back-navigation and bookmarks restore the exact view.
 *
 * URL param schema:
 *   q       = search query text
 *   mode    = lexical | semantic | metadata
 *   group   = scene | video
 *   sort    = relevance | latest | alpha_asc | alpha_desc
 *   page    = page number (1-based)
 *   sources = comma-separated source types (gdrive,local,removable_disk)
 *   ds      = date start (YYYY-MM-DD)
 *   de      = date end (YYYY-MM-DD)
 */

import type { ReadonlyURLSearchParams } from "next/navigation";
import type { SearchMode } from "@/lib/types/search";

// ── Types ────────────────────────────────────────────────────────────────

export type GroupBy = "video" | "scene";
export type SortOption = "relevance" | "latest" | "alpha_asc" | "alpha_desc";
export type SourceType = "gdrive" | "removable_disk" | "local";

export interface DashboardSearchState {
  query: string;
  searchMode: SearchMode;
  groupBy: GroupBy;
  sortBy: SortOption;
  currentPage: number;
  sourceFilters: ReadonlySet<SourceType>;
  dateStart: Date | null;
  dateEnd: Date | null;
}

// ── Constants ────────────────────────────────────────────────────────────

export const ALL_SOURCES: readonly SourceType[] = [
  "gdrive",
  "removable_disk",
  "local",
] as const;

const VALID_SEARCH_MODES: readonly SearchMode[] = [
  "metadata",
  "lexical",
  "semantic",
];
const VALID_GROUP_BY: readonly GroupBy[] = ["video", "scene"];
const VALID_SORT_OPTIONS: readonly SortOption[] = [
  "relevance",
  "latest",
  "alpha_asc",
  "alpha_desc",
];

const DEFAULT_STATE: DashboardSearchState = {
  query: "",
  searchMode: "lexical",
  groupBy: "scene",
  sortBy: "latest",
  currentPage: 1,
  sourceFilters: new Set(ALL_SOURCES),
  dateStart: null,
  dateEnd: null,
};

// ── Param keys ───────────────────────────────────────────────────────────

const PARAM = {
  QUERY: "q",
  MODE: "mode",
  GROUP: "group",
  SORT: "sort",
  PAGE: "page",
  SOURCES: "sources",
  DATE_START: "ds",
  DATE_END: "de",
} as const;

// ── Helpers ──────────────────────────────────────────────────────────────

function formatDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function parseDate(s: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return null;
  const d = new Date(s + "T00:00:00");
  return isNaN(d.getTime()) ? null : d;
}

function isValidEnum<T extends string>(
  value: string | null,
  valid: readonly T[],
): value is T {
  return value !== null && (valid as readonly string[]).includes(value);
}

// ── Serialize ────────────────────────────────────────────────────────────

/**
 * Convert dashboard state to URL search params.
 * Only includes non-default values to keep URLs clean.
 */
export function serializeSearchState(
  state: DashboardSearchState,
): URLSearchParams {
  const params = new URLSearchParams();

  if (state.query) {
    params.set(PARAM.QUERY, state.query);
  }
  if (state.searchMode !== DEFAULT_STATE.searchMode) {
    params.set(PARAM.MODE, state.searchMode);
  }
  if (state.groupBy !== DEFAULT_STATE.groupBy) {
    params.set(PARAM.GROUP, state.groupBy);
  }
  if (state.sortBy !== DEFAULT_STATE.sortBy) {
    params.set(PARAM.SORT, state.sortBy);
  }
  if (state.currentPage > 1) {
    params.set(PARAM.PAGE, String(state.currentPage));
  }

  // Only serialize sources if not all are selected
  const allSelected =
    state.sourceFilters.size === ALL_SOURCES.length &&
    ALL_SOURCES.every((s) => state.sourceFilters.has(s));
  if (!allSelected && state.sourceFilters.size > 0) {
    const sorted = ALL_SOURCES.filter((s) => state.sourceFilters.has(s));
    params.set(PARAM.SOURCES, sorted.join(","));
  }

  if (state.dateStart) {
    params.set(PARAM.DATE_START, formatDate(state.dateStart));
  }
  if (state.dateEnd) {
    params.set(PARAM.DATE_END, formatDate(state.dateEnd));
  }

  return params;
}

// ── Deserialize ──────────────────────────────────────────────────────────

export function deserializeSearchState(
  params: URLSearchParams | ReadonlyURLSearchParams,
): DashboardSearchState {
  const modeRaw = params.get(PARAM.MODE);
  const groupRaw = params.get(PARAM.GROUP);
  const sortRaw = params.get(PARAM.SORT);
  const pageRaw = params.get(PARAM.PAGE);
  const sourcesRaw = params.get(PARAM.SOURCES);
  const dsRaw = params.get(PARAM.DATE_START);
  const deRaw = params.get(PARAM.DATE_END);

  // Sources
  let sourceFilters: Set<SourceType>;
  if (sourcesRaw !== null) {
    const parsed = sourcesRaw
      .split(",")
      .filter((s): s is SourceType =>
        ALL_SOURCES.includes(s as SourceType),
      );
    sourceFilters = parsed.length > 0 ? new Set(parsed) : new Set(ALL_SOURCES);
  } else {
    sourceFilters = new Set(ALL_SOURCES);
  }

  // Page
  let currentPage = 1;
  if (pageRaw !== null) {
    const n = parseInt(pageRaw, 10);
    if (!isNaN(n) && n >= 1) currentPage = n;
  }

  // Dates
  const dateStart = dsRaw ? parseDate(dsRaw) : null;
  const dateEnd = deRaw ? parseDate(deRaw) : null;

  return {
    query: params.get(PARAM.QUERY) ?? "",
    searchMode: isValidEnum(modeRaw, VALID_SEARCH_MODES)
      ? modeRaw
      : DEFAULT_STATE.searchMode,
    groupBy: isValidEnum(groupRaw, VALID_GROUP_BY)
      ? groupRaw
      : DEFAULT_STATE.groupBy,
    sortBy: isValidEnum(sortRaw, VALID_SORT_OPTIONS)
      ? sortRaw
      : DEFAULT_STATE.sortBy,
    currentPage,
    sourceFilters,
    dateStart,
    dateEnd,
  };
}

export function hasSearchParams(params: URLSearchParams | ReadonlyURLSearchParams): boolean {
  return params.has(PARAM.QUERY);
}
