/**
 * GA4 (gtag.js) helper — thin wrapper over window.gtag().
 *
 * Measurement ID is read from NEXT_PUBLIC_GA_MEASUREMENT_ID.
 * When the env var is empty the helpers become no-ops,
 * so the rest of the codebase can call them unconditionally.
 */

export const GA_MEASUREMENT_ID = process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID ?? "";

/* eslint-disable @typescript-eslint/no-explicit-any */
declare global {
  interface Window {
    gtag?: (...args: any[]) => void;
    dataLayer?: any[];
  }
}

function gtag(...args: any[]) {
  if (typeof window === "undefined" || !window.gtag) return;
  window.gtag(...args);
}

// ---------------------------------------------------------------------------
// Page view (auto-tracked by gtag.js, but exposed for SPA route changes)
// ---------------------------------------------------------------------------
export function pageview(url: string) {
  gtag("config", GA_MEASUREMENT_ID, { page_path: url });
}

// ---------------------------------------------------------------------------
// Color search events
// ---------------------------------------------------------------------------

/** Fired when user selects a color family chip. */
export function trackColorSearch(colorFamily: string, hasQuery: boolean) {
  gtag("event", "color_search", {
    color_family: colorFamily,
    has_query: String(hasQuery),
  });
}

/** Fired when user navigates to a new page of search results (pagination / "더보기"). */
export function trackSearchPageView(params: {
  pageNumber: number;
  colorFamily?: string;
  query?: string;
}) {
  gtag("event", "search_page_view", {
    page_number: params.pageNumber,
    color_family: params.colorFamily ?? "",
    query: params.query ?? "",
  });
}

/** Fired when user clicks a search result. */
export function trackSearchResultClick(params: {
  pageNumber: number;
  position: number;
  colorFamily?: string;
  query?: string;
  videoId?: string;
}) {
  gtag("event", "search_result_click", {
    page_number: params.pageNumber,
    position: params.position,
    color_family: params.colorFamily ?? "",
    query: params.query ?? "",
    video_id: params.videoId ?? "",
  });
}
