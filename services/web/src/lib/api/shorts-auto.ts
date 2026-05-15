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
 * Feature-detect probe. Hits the dedicated availability endpoint which
 * checks the master flag BEFORE any body validation, so the 200/404
 * signal is reliable. Returns true on any non-404 response (including
 * 401/5xx/network errors) so transient failures don't hide CTAs.
 */
export async function probeAutoShortsAvailability(
  getToken: TokenGetter,
): Promise<boolean> {
  const headers = await authHeaders(getToken);
  try {
    const res = await fetch(`${getApiBaseUrl()}/api/shorts/auto-availability`, {
      method: "GET",
      headers,
    });
    if (res.status === 404) return false;
    return true;
  } catch {
    return true;
  }
}

/**
 * Richer availability probe that returns both ``enabled`` and
 * ``llm_enabled`` flags. Used by the UI to decide whether to show the
 * "AI mode" toggle. Falls back to ``{enabled: true, llm_enabled: false}``
 * on any non-404 error (same as the simpler probe — never hide CTAs
 * on transient failures, but don't silently claim AI is available).
 */
export async function fetchAutoShortsAvailability(
  getToken: TokenGetter,
): Promise<{ enabled: boolean; llm_enabled: boolean }> {
  const headers = await authHeaders(getToken);
  try {
    const res = await fetch(`${getApiBaseUrl()}/api/shorts/auto-availability`, {
      method: "GET",
      headers,
    });
    if (res.status === 404) return { enabled: false, llm_enabled: false };
    if (!res.ok) return { enabled: true, llm_enabled: false };
    const body = (await res.json()) as Partial<{ enabled: boolean; llm_enabled: boolean }>;
    return {
      enabled: body.enabled ?? true,
      llm_enabled: body.llm_enabled ?? false,
    };
  } catch {
    return { enabled: true, llm_enabled: false };
  }
}
