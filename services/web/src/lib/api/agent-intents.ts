import { ApiError } from "@/lib/types";
import type { AgentIntentResponse } from "@/lib/types";
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
    const response = await fetch(`${getApiBaseUrl()}${endpoint}`, {
      method,
      headers,
      ...(body ? { body: JSON.stringify(body) } : {}),
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

export async function createFolderIntent(
  getToken: TokenGetter,
  deviceId: string,
): Promise<AgentIntentResponse> {
  return apiRequest<AgentIntentResponse>(
    "/api/agent-intents/",
    "POST",
    getToken,
    { type: "folder_add", device_id: deviceId },
  );
}
