import {
  ApiError,
  VideoFilters,
  VideoListResponse,
  VideoScenesResponse,
  VideoStats,
} from "@/lib/types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL;

type TokenGetter = () => Promise<string | null>;

async function apiGet<T>(
  endpoint: string,
  getToken?: TokenGetter,
): Promise<T> {
  if (!API_BASE_URL) {
    throw new ApiError(
      "tenancy",
      0,
      "NEXT_PUBLIC_API_URL is not configured. " +
        "Set it to http://{org}.app.heimdex.local:8000",
    );
  }

  const headers: Record<string, string> = {};

  if (getToken) {
    try {
      const token = await getToken();
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
    } catch (err) {
      console.warn("[Heimdex] Failed to get access token:", err);
    }
  }

  try {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, { headers });

    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw ApiError.fromResponse(response.status, body);
    }

    return response.json();
  } catch (err) {
    if (err instanceof ApiError) {
      throw err;
    }
    throw new ApiError(
      "network",
      0,
      "Network error. Check your connection and try again.",
    );
  }
}

/**
 * List ingested videos with optional filters and cursor pagination.
 */
export async function getVideos(
  filters?: VideoFilters,
  getToken?: TokenGetter,
): Promise<VideoListResponse> {
  const params = new URLSearchParams();
  if (filters?.library_id) params.set("library_id", filters.library_id);
  if (filters?.source_type) params.set("source_type", filters.source_type);
  if (filters?.sort) params.set("sort", filters.sort);
  if (filters?.page_size) params.set("page_size", String(filters.page_size));
  if (filters?.after) params.set("after", filters.after);

  const qs = params.toString();
  return apiGet<VideoListResponse>(
    `/api/videos${qs ? `?${qs}` : ""}`,
    getToken,
  );
}

/**
 * Get scenes for a specific video.
 */
export async function getVideoScenes(
  videoId: string,
  pageSize?: number,
  offset?: number,
  getToken?: TokenGetter,
): Promise<VideoScenesResponse> {
  const params = new URLSearchParams();
  if (pageSize !== undefined) params.set("page_size", String(pageSize));
  if (offset !== undefined) params.set("offset", String(offset));

  const qs = params.toString();
  return apiGet<VideoScenesResponse>(
    `/api/videos/${encodeURIComponent(videoId)}/scenes${qs ? `?${qs}` : ""}`,
    getToken,
  );
}

/**
 * Get aggregate video ingestion statistics.
 */
export async function getVideoStats(
  getToken?: TokenGetter,
): Promise<VideoStats> {
  return apiGet<VideoStats>("/api/videos/stats", getToken);
}
