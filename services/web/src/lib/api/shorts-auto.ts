// ============================================================================
// Auto-Shorts API client — mirrors shorts-render.ts style:
//   - plain fetch + getApiBaseUrl
//   - Bearer token via TokenGetter
//   - custom error subclasses for rate-limit / feature-disabled so the UI
//     can branch on `err.isRateLimit` / `err.isFeatureDisabled` without
//     parsing error strings.
//
// NEVER import from features/*. This is the one-way public surface the
// feature directory consumes.
// ============================================================================

import { getApiBaseUrl } from "./utils";
import type {
  AutoRenderRequest,
  AutoSelectRequest,
  AutoSelectResponse,
} from "../types/shorts-auto";
import type { RenderJobResponse } from "./highlight-reel";

export type { RenderJobResponse };

type TokenGetter = () => Promise<string | null>;

export class AutoShortsRateLimitError extends Error {
  readonly isRateLimit = true;
  constructor(message: string) {
    super(message);
    this.name = "AutoShortsRateLimitError";
  }
}

/**
 * Thrown when the backend feature flag is off (router returns 404). UI
 * should render a neutral "unavailable" state and, when detected during
 * feature-availability probing, suppress entry-point CTAs.
 */
export class AutoShortsFeatureDisabledError extends Error {
  readonly isFeatureDisabled = true;
  constructor(message: string) {
    super(message);
    this.name = "AutoShortsFeatureDisabledError";
  }
}

/**
 * 422 responses carry a human-readable `detail`. Callers surface this
 * verbatim — the backend already writes user-appropriate copy
 * (e.g. "insufficient qualifying clips: requested 5, found 2").
 */
export class AutoShortsValidationError extends Error {
  readonly isValidation = true;
  readonly status = 422;
  constructor(message: string) {
    super(message);
    this.name = "AutoShortsValidationError";
  }
}

async function authHeaders(getToken: TokenGetter): Promise<Record<string, string>> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  try {
    const token = await getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  } catch {
    /* noop */
  }
  return headers;
}

async function parseError(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    return typeof body?.detail === "string" ? body.detail : fallback;
  } catch {
    return fallback;
  }
}

async function mapStatusToError(res: Response, fallback: string): Promise<Error> {
  const detail = await parseError(res, fallback);
  if (res.status === 404) return new AutoShortsFeatureDisabledError(detail);
  if (res.status === 429) return new AutoShortsRateLimitError(detail);
  if (res.status === 422) return new AutoShortsValidationError(detail);
  return new Error(`${detail} (${res.status})`);
}

export async function postAutoSelect(
  body: AutoSelectRequest,
  getToken: TokenGetter,
): Promise<AutoSelectResponse> {
  const headers = await authHeaders(getToken);
  const res = await fetch(`${getApiBaseUrl()}/api/shorts/auto-select`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw await mapStatusToError(res, "Auto-select failed");
  }
  return res.json();
}

export async function postAutoRender(
  body: AutoRenderRequest,
  getToken: TokenGetter,
): Promise<RenderJobResponse> {
  const headers = await authHeaders(getToken);
  const res = await fetch(`${getApiBaseUrl()}/api/shorts/auto-render`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw await mapStatusToError(res, "Auto-render failed");
  }
  return res.json();
}

/**
 * Lightweight feature-detect. Calls auto-select with a deliberately
 * invalid body so the backend short-circuits to 422 or 404:
 *   - 404 → feature is disabled
 *   - any 4xx other than 404 → feature is enabled (our bad input)
 *   - 401/503 → treat as available to avoid hiding CTAs on transient
 *     errors; real failures surface on the actual request.
 *
 * Cheaper than a dedicated /api/config endpoint (zero backend changes)
 * and the 422 path means we don't consume rate-limit budget on a
 * successful call.
 */
export async function probeAutoShortsAvailability(
  getToken: TokenGetter,
): Promise<boolean> {
  const headers = await authHeaders(getToken);
  try {
    const res = await fetch(`${getApiBaseUrl()}/api/shorts/auto-select`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        // Intentionally malformed — triggers a 422 if the feature is live
        // and a 404 when the flag is off. Any 5xx or network error also
        // falls through to "available" so we don't hide the feature on
        // transient issues.
        video_id: "",
        mode: "both",
      }),
    });
    if (res.status === 404) return false;
    return true;
  } catch {
    return true;
  }
}
