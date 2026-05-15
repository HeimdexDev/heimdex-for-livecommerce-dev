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

/** Fired when search results render (initial search + pagination / "더보기").
 *  Empty params are omitted so GA4 BQ `IS NOT NULL` filters behave correctly. */
export function trackSearchPageView(params: {
  pageNumber: number;
  colorFamily?: string;
  query?: string;
}) {
  const eventParams: Record<string, unknown> = { page_number: params.pageNumber };
  if (params.colorFamily) eventParams.color_family = params.colorFamily;
  if (params.query) eventParams.query = params.query;
  gtag("event", "search_page_view", eventParams);
}

/** Fired when user clicks a search result. */
export function trackSearchResultClick(params: {
  pageNumber: number;
  position: number;
  colorFamily?: string;
  query?: string;
  videoId?: string;
}) {
  const eventParams: Record<string, unknown> = {
    page_number: params.pageNumber,
    position: params.position,
  };
  if (params.colorFamily) eventParams.color_family = params.colorFamily;
  if (params.query) eventParams.query = params.query;
  if (params.videoId) eventParams.video_id = params.videoId;
  gtag("event", "search_result_click", eventParams);
}
