import { ApiError } from "@/lib/types";
import { getApiBaseUrl } from "./utils";

type TokenGetter = () => Promise<string | null>;

async function apiRequest<T>(
  endpoint: string,
  method: string,
  getToken?: TokenGetter,
  body?: unknown,
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
    const init: RequestInit = { method, headers };
    if (body !== undefined) {
      init.body = JSON.stringify(body);
    }

    const response = await fetch(`${getApiBaseUrl()}${endpoint}`, init);

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

export interface OrgSettingsResponse {
  thumbnail_aspect_ratio: string;
}

export interface OrgSettingsUpdateRequest {
  thumbnail_aspect_ratio?: "16:9" | "9:16";
}

export async function getOrgSettings(
  getToken?: TokenGetter,
): Promise<OrgSettingsResponse> {
  return apiRequest<OrgSettingsResponse>("/api/org/settings", "GET", getToken);
}

export async function updateOrgSettings(
  request: OrgSettingsUpdateRequest,
  getToken?: TokenGetter,
): Promise<OrgSettingsResponse> {
  return apiRequest<OrgSettingsResponse>("/api/org/settings", "PATCH", getToken, request);
}
