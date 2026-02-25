import {
  ApiError,
  ExcludePreferencesResponse,
  PeopleListResponse,
  PersonVideosResponse,
  RenamePersonResponse,
} from "@/lib/types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

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

    const response = await fetch(`${API_BASE_URL}${endpoint}`, init);

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

export async function getPeople(
  getToken?: TokenGetter,
): Promise<PeopleListResponse> {
  return apiRequest<PeopleListResponse>("/api/people", "GET", getToken);
}

export async function renamePerson(
  personClusterId: string,
  label: string | null,
  getToken?: TokenGetter,
): Promise<RenamePersonResponse> {
  return apiRequest<RenamePersonResponse>(
    `/api/people/${encodeURIComponent(personClusterId)}`,
    "PATCH",
    getToken,
    { label },
  );
}

export async function deletePerson(
  personClusterId: string,
  getToken?: TokenGetter,
): Promise<void> {
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
    const response = await fetch(
      `${API_BASE_URL}/api/people/${encodeURIComponent(personClusterId)}`,
      { method: "DELETE", headers },
    );

    if (!response.ok && response.status !== 204) {
      const responseBody = await response.json().catch(() => null);
      throw ApiError.fromResponse(response.status, responseBody);
    }
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

export async function getPersonVideos(
  personClusterId: string,
  getToken?: TokenGetter,
): Promise<PersonVideosResponse> {
  return apiRequest<PersonVideosResponse>(
    `/api/people/${encodeURIComponent(personClusterId)}/videos`,
    "GET",
    getToken,
  );
}

export async function getExcludePreferences(
  getToken?: TokenGetter,
): Promise<ExcludePreferencesResponse> {
  return apiRequest<ExcludePreferencesResponse>(
    "/api/people/exclude-preferences",
    "GET",
    getToken,
  );
}

export async function saveExcludePreferences(
  personClusterIds: string[],
  getToken?: TokenGetter,
): Promise<ExcludePreferencesResponse> {
  return apiRequest<ExcludePreferencesResponse>(
    "/api/people/exclude-preferences",
    "PUT",
    getToken,
    { person_cluster_ids: personClusterIds },
  );
}
