import {
  ApiError,
  ShortsPlanRequest,
  ShortsPlanResponse,
} from "@/lib/types";
import { getApiBaseUrl } from "./utils";

type TokenGetter = () => Promise<string | null>;

async function apiPost<T>(
  endpoint: string,
  body?: unknown,
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
      body: JSON.stringify(body ?? {}),
    });

    if (!response.ok) {
      const responseBody = await response.json().catch(() => null);
      throw ApiError.fromResponse(response.status, responseBody);
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

export async function generateShortsPlan(
  videoId: string,
  request?: ShortsPlanRequest,
  getToken?: TokenGetter,
): Promise<ShortsPlanResponse> {
  return apiPost<ShortsPlanResponse>(
    `/api/videos/${encodeURIComponent(videoId)}/shorts/plan`,
    request,
    getToken,
  );
}
