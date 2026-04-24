import { ApiError, SearchRequest, SearchResponse, SceneSearchResponse } from "@/lib/types";
import { getApiBaseUrl } from "./utils";

type TokenGetter = () => Promise<string | null>;

/**
 * Thrown when the backend returns 429 on a search request. Carries the
 * ``Retry-After`` header value so the UI can render an accurate
 * countdown. Callers should NOT blank the existing ``searchResponse``
 * on this error — the previous page is still valid, just the latest
 * fetch was throttled. Mirrors ``AutoShortsRateLimitError``.
 */
export class SearchRateLimitError extends Error {
  readonly isRateLimit = true;
  readonly retryAfterSeconds: number;
  readonly status = 429;
  constructor(message: string, retryAfterSeconds: number) {
    super(message);
    this.name = "SearchRateLimitError";
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

/**
 * Make an authenticated API request.
 */
async function apiRequest<T>(
  endpoint: string,
  options: RequestInit,
  getToken?: TokenGetter
): Promise<T> {
  // Build headers
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...options.headers,
  };

  // Attach auth token if available
  if (getToken) {
    try {
      const token = await getToken();
      if (token) {
        (headers as Record<string, string>)["Authorization"] = `Bearer ${token}`;
      }
    } catch (err) {
      console.warn("[Heimdex] Failed to get access token:", err);
      // Continue without token - API will return 401 if auth is required
    }
  }

  try {
    const response = await fetch(`${getApiBaseUrl()}${endpoint}`, {
      ...options,
      headers,
    });

    if (response.status === 429) {
      const retryHeader = response.headers.get("Retry-After");
      const parsed = Number(retryHeader);
      const retryAfter = Number.isFinite(parsed) && parsed > 0 ? parsed : 60;
      const body = await response.json().catch(() => null);
      throw new SearchRateLimitError(
        (body && typeof body.detail === "string" && body.detail) ||
          "Search rate limit exceeded. Try again in a moment.",
        retryAfter,
      );
    }

    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw ApiError.fromResponse(response.status, body);
    }

    return response.json();
  } catch (err) {
    if (err instanceof SearchRateLimitError) {
      throw err;
    }
    if (err instanceof ApiError) {
      throw err;
    }
    // Network error
    throw new ApiError(
      "network",
      0,
      "Network error. Check your connection and try again."
    );
  }
}

/**
 * Search for video segments.
 * 
 * @param request - Search parameters
 * @param getToken - Optional function to get auth token
 */
export async function search(
  request: SearchRequest,
  getToken?: TokenGetter
): Promise<SearchResponse> {
  return apiRequest<SearchResponse>(
    "/api/search",
    {
      method: "POST",
      body: JSON.stringify(request),
    },
    getToken
  );
}

/**
 * Search function that doesn't require authentication (for backward compatibility).
 * Will fail with 401 if the backend requires auth.
 */
export async function searchUnauthenticated(
  request: SearchRequest
): Promise<SearchResponse> {
  return search(request);
}

export async function searchScenes(
  request: SearchRequest,
  getToken?: TokenGetter
): Promise<SceneSearchResponse> {
  return apiRequest<SceneSearchResponse>(
    "/api/search/scenes",
    {
      method: "POST",
      body: JSON.stringify(request),
    },
    getToken
  );
}
