import { useEffect, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  type ContentTypeFilter,
  type DashboardSearchState,
  serializeSearchState,
} from "@/lib/search-state";

interface UseURLSyncOptions {
  /** When set, this content type is excluded from URL serialization */
  lockedContentType?: ContentTypeFilter;
}

/**
 * Sync DashboardSearchState to the browser URL.
 *
 * Uses `router.replace` (not push) to avoid polluting history.
 * Skips the first render to prevent a redundant replace on mount.
 * When `lockedContentType` is provided, the content type param is
 * omitted from the URL (e.g., /images doesn't need ?type=image).
 */
export function useURLSync(
  state: DashboardSearchState,
  options?: UseURLSyncOptions,
): void {
  const router = useRouter();
  const pathname = usePathname();
  const isInitialRender = useRef(true);

  useEffect(() => {
    if (isInitialRender.current) {
      isInitialRender.current = false;
      return;
    }
    const stateForUrl: DashboardSearchState = options?.lockedContentType
      ? { ...state, contentType: "all" }
      : state;
    const params = serializeSearchState(stateForUrl);
    const paramString = params.toString();
    const newUrl = paramString ? `${pathname}?${paramString}` : pathname;
    router.replace(newUrl, { scroll: false });
  }, [
    state.query,
    state.searchMode,
    state.groupBy,
    state.sortBy,
    state.contentType,
    state.referenceMode,
    state.currentPage,
    state.sourceFilters,
    state.dateStart,
    state.dateEnd,
    options?.lockedContentType,
    router,
    pathname,
  ]);
}
