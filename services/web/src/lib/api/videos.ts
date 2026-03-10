import {
  ApiError,
  VideoFilters,
  VideoListResponse,
  VideoScenesResponse,
  VideoStats,
} from "@/lib/types";
import { API_BASE_URL } from "./utils";

type TokenGetter = () => Promise<string | null>;

async function apiGet<T>(
  endpoint: string,
  getToken?: TokenGetter,
): Promise<T> {
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
  if (filters?.source_types?.length) params.set("source_types", filters.source_types.join(","));
  else if (filters?.source_type) params.set("source_type", filters.source_type);
  if (filters?.date_from) params.set("date_from", filters.date_from);
  if (filters?.date_to) params.set("date_to", filters.date_to);
  if (filters?.content_types?.length) params.set("content_types", filters.content_types.join(","));
  if (filters?.sort) params.set("sort", filters.sort);
  if (filters?.page_size) params.set("page_size", String(filters.page_size));
  if (filters?.after) params.set("after", filters.after);

  const qs = params.toString();
  return apiGet<VideoListResponse>(
    `/api/videos${qs ? `?${qs}` : ""}`,
    getToken,
  );
}

export async function getVideoScenes(
  videoId: string,
  pageSize?: number,
  offset?: number,
  getToken?: TokenGetter,
  query?: string,
): Promise<VideoScenesResponse> {
  const params = new URLSearchParams();
  if (pageSize !== undefined) params.set("page_size", String(pageSize));
  if (offset !== undefined) params.set("offset", String(offset));
  if (query) params.set("q", query);

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
