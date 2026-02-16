import {
  SearchRequest,
  SearchResponse,
  SceneSearchResponse,
  VideoFilters,
  VideoListResponse,
  VideoScenesResponse,
  VideoStats,
  ApiError,
} from "@/lib/types";

export interface ApiClient {
  search(request: SearchRequest): Promise<SearchResponse>;
  searchScenes(request: SearchRequest): Promise<SceneSearchResponse>;
  getVideos(filters?: VideoFilters): Promise<VideoListResponse>;
  getVideoScenes(videoId: string, pageSize?: number, offset?: number): Promise<VideoScenesResponse>;
  getVideoStats(): Promise<VideoStats>;
}

export interface ApiClientConfig {
  baseUrl: string;
  getAccessToken: () => Promise<string | null>;
}

export function createApiClient(config: ApiClientConfig): ApiClient {
  const { baseUrl, getAccessToken } = config;

  async function request<T>(endpoint: string, options: RequestInit): Promise<T> {
    if (!baseUrl) {
      throw new ApiError(
        "tenancy",
        0,
        "NEXT_PUBLIC_API_URL is not configured."
      );
    }

    const headers: HeadersInit = {
      "Content-Type": "application/json",
      ...options.headers,
    };

    try {
      const token = await getAccessToken();
      if (token) {
        (headers as Record<string, string>)["Authorization"] = `Bearer ${token}`;
      }
    } catch (err) {
      console.warn("[Heimdex] Failed to get access token:", err);
    }

    try {
      const response = await fetch(`${baseUrl}${endpoint}`, {
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
      throw new ApiError("network", 0, "Network error. Check your connection.");
    }
  }

  function buildQs(params: Record<string, string | undefined>): string {
    const sp = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined) sp.set(k, v);
    }
    const qs = sp.toString();
    return qs ? `?${qs}` : "";
  }

  return {
    search: (req: SearchRequest) =>
      request<SearchResponse>("/api/search", {
        method: "POST",
        body: JSON.stringify(req),
      }),
    searchScenes: (req: SearchRequest) =>
      request<SceneSearchResponse>("/api/search/scenes", {
        method: "POST",
        body: JSON.stringify(req),
      }),
    getVideos: (filters?: VideoFilters) => {
      const qs = buildQs({
        library_id: filters?.library_id,
        source_type: filters?.source_type,
        sort: filters?.sort,
        page_size: filters?.page_size !== undefined ? String(filters.page_size) : undefined,
        after: filters?.after,
      });
      return request<VideoListResponse>(`/api/videos${qs}`, { method: "GET" });
    },
    getVideoScenes: (videoId: string, pageSize?: number, offset?: number) => {
      const qs = buildQs({
        page_size: pageSize !== undefined ? String(pageSize) : undefined,
        offset: offset !== undefined ? String(offset) : undefined,
      });
      return request<VideoScenesResponse>(
        `/api/videos/${encodeURIComponent(videoId)}/scenes${qs}`,
        { method: "GET" },
      );
    },
    getVideoStats: () =>
      request<VideoStats>("/api/videos/stats", { method: "GET" }),
  };
}
