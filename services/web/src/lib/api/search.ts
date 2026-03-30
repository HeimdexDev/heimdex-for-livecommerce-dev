import { ApiError, SearchRequest, SearchResponse, SceneSearchResponse } from "@/lib/types";
import { getApiBaseUrl } from "./utils";

type TokenGetter = () => Promise<string | null>;

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

    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw ApiError.fromResponse(response.status, body);
    }

    return response.json();
  } catch (err) {
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
