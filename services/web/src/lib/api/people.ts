import {
  ApiError,
  BulkDeleteRequest,
  BulkDeleteResponse,
  ExcludePreferencesResponse,
  MergePersonRequest,
  MergePersonResponse,
  PeopleListResponse,
  PersonTimelineResponse,
  PersonVideosResponse,
  RenamePersonResponse,
  VideoExclusionsResponse,
} from "@/lib/types";
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

export async function getPeople(
  getToken?: TokenGetter,
  query?: string,
): Promise<PeopleListResponse> {
  const params = query ? `?q=${encodeURIComponent(query)}` : "";
  return apiRequest<PeopleListResponse>(`/api/people${params}`, "GET", getToken);
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
      `${getApiBaseUrl()}/api/people/${encodeURIComponent(personClusterId)}`,
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

export async function bulkDeletePeople(
  request: BulkDeleteRequest,
  getToken?: TokenGetter,
): Promise<BulkDeleteResponse> {
  return apiRequest<BulkDeleteResponse>(
    "/api/people/bulk-delete",
    "POST",
    getToken,
    request,
  );
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

export async function getPersonTimeline(
  personClusterId: string,
  getToken?: TokenGetter,
): Promise<PersonTimelineResponse> {
  return apiRequest<PersonTimelineResponse>(
    `/api/people/${encodeURIComponent(personClusterId)}/timeline`,
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

export async function getVideoExclusions(
  personClusterId: string,
  getToken?: TokenGetter,
): Promise<VideoExclusionsResponse> {
  return apiRequest<VideoExclusionsResponse>(
    `/api/people/${encodeURIComponent(personClusterId)}/video-exclusions`,
    "GET",
    getToken,
  );
}

export async function saveVideoExclusions(
  personClusterId: string,
  excludedVideoIds: string[],
  getToken?: TokenGetter,
): Promise<VideoExclusionsResponse> {
  return apiRequest<VideoExclusionsResponse>(
    `/api/people/${encodeURIComponent(personClusterId)}/video-exclusions`,
    "PUT",
    getToken,
    { excluded_video_ids: excludedVideoIds },
  );
}

export async function mergePeople(
  request: MergePersonRequest,
  getToken?: TokenGetter,
): Promise<MergePersonResponse> {
  return apiRequest<MergePersonResponse>(
    "/api/people/merge",
    "POST",
    getToken,
    request,
  );
}
