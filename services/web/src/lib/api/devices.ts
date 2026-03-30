import { ApiError, DeviceListResponse, PairingCodeResponse } from "@/lib/types";
import { getApiBaseUrl } from "./utils";

type TokenGetter = () => Promise<string | null>;

async function apiRequest<T>(
  endpoint: string,
  method: string,
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
      method,
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
    throw new ApiError(
      "network",
      0,
      "Network error. Check your connection and try again.",
    );
  }
}

export async function getDevices(
  getToken?: TokenGetter,
): Promise<DeviceListResponse> {
  return apiRequest<DeviceListResponse>("/api/devices/", "GET", getToken);
}

export async function createPairingCode(
  getToken?: TokenGetter,
): Promise<PairingCodeResponse> {
  return apiRequest<PairingCodeResponse>(
    "/api/devices/pairing-code",
    "POST",
    getToken,
  );
}
