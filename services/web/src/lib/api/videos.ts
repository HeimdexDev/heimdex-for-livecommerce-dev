import {
  ApiError,
  ReprocessJobResponse,
  ReprocessParams,
  SceneGroupsResponse,
  VideoFilters,
  VideoListResponse,
  VideoScenesResponse,
  VideoStats,
  VideoPeopleResponse,
} from "@/lib/types";
import { getApiBaseUrl } from "./utils";

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
    const response = await fetch(`${getApiBaseUrl()}${endpoint}`, { headers });

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

async function apiPost<T>(
  endpoint: string,
  body: unknown,
  getToken?: TokenGetter,
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

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
    const response = await fetch(`${getApiBaseUrl()}${endpoint}`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const errorBody = await response.json().catch(() => null);
      throw ApiError.fromResponse(response.status, errorBody);
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

export async function reprocessScenes(
  videoId: string,
  params: ReprocessParams,
  getToken: TokenGetter,
): Promise<ReprocessJobResponse> {
  return apiPost<ReprocessJobResponse>(
    `/api/videos/${encodeURIComponent(videoId)}/reprocess`,
    params,
    getToken,
  );
}

export async function getReprocessStatus(
  videoId: string,
  getToken: TokenGetter,
): Promise<ReprocessJobResponse | null> {
  const headers: Record<string, string> = {};

  try {
    const token = await getToken();
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
  } catch (err) {
    console.warn("[Heimdex] Failed to get access token:", err);
  }

  try {
    const response = await fetch(`${getApiBaseUrl()}/api/videos/${encodeURIComponent(videoId)}/reprocess`, { headers });

    if (!response.ok) {
      if (response.status === 404) return null;
      const body = await response.json().catch(() => null);
      throw ApiError.fromResponse(response.status, body);
    }

    const text = await response.text();
    if (!text) return null;
    return JSON.parse(text);
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

export async function getVideoPeople(
  videoId: string,
  getToken?: TokenGetter,
): Promise<VideoPeopleResponse> {
  return apiGet<VideoPeopleResponse>(
    `/api/videos/${encodeURIComponent(videoId)}/people`,
    getToken,
  );
}

export async function getVideoSceneGroups(
  videoId: string,
  threshold?: number,
  getToken?: TokenGetter,
): Promise<SceneGroupsResponse> {
  const params = new URLSearchParams();
  if (threshold !== undefined) params.set("threshold", String(threshold));
  const qs = params.toString();
  return apiGet<SceneGroupsResponse>(
    `/api/videos/${encodeURIComponent(videoId)}/scene-groups${qs ? `?${qs}` : ""}`,
    getToken,
  );
}
