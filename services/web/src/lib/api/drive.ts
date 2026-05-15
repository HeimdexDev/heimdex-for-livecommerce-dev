import {
  ApiError,
  DriveStatusResponse,
  DriveConnectionResponse,
  DriveFolderListResponse,
  DriveOAuthStatus,
  BrowseFoldersResponse,
  SyncTriggerResponse,
  DriveSyncProgress,
} from "@/lib/types";
import type { FolderTreeResponse, ToggleFolderResponse, WatchedFolder, FolderDisableImpact } from "@/lib/types/drive";
import { getApiBaseUrl } from "./utils";

type TokenGetter = () => Promise<string | null>;

export async function getDriveStatus(
  getToken?: TokenGetter,
): Promise<DriveStatusResponse> {
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
    const response = await fetch(`${getApiBaseUrl()}/api/drive/status`, {
      method: "GET",
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

export async function getDriveConnections(
  getToken?: TokenGetter,
): Promise<DriveConnectionResponse[]> {
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
    const response = await fetch(`${getApiBaseUrl()}/api/drive/connections`, {
      method: "GET",
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

export async function triggerDriveSync(
  connectionId: string,
  getToken?: TokenGetter,
): Promise<SyncTriggerResponse> {
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
    const response = await fetch(
      `${getApiBaseUrl()}/api/drive/connections/${connectionId}/sync`,
      {
        method: "POST",
        headers,
        body: JSON.stringify({}),
      },
    );

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

export async function getDriveFolders(
  connectionId: string,
  getToken?: TokenGetter,
): Promise<DriveFolderListResponse> {
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
    const response = await fetch(
      `${getApiBaseUrl()}/api/drive/connections/${connectionId}/folders`,
      {
        method: "GET",
        headers,
      },
    );

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

async function _buildHeaders(getToken?: TokenGetter): Promise<Record<string, string>> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (getToken) {
    try {
      const token = await getToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;
    } catch (err) {
      console.warn("[Heimdex] Failed to get access token:", err);
    }
  }
  return headers;
}

export async function getOAuthStatus(
  getToken?: TokenGetter,
): Promise<DriveOAuthStatus> {
  const headers = await _buildHeaders(getToken);
  try {
    const response = await fetch(`${getApiBaseUrl()}/api/drive/oauth/status`, {
      method: "GET",
      headers,
    });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw ApiError.fromResponse(response.status, body);
    }
    return response.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError("network", 0, "Network error.");
  }
}

export async function getOAuthAuthorizeUrl(
  getToken?: TokenGetter,
): Promise<{ authorize_url: string }> {
  const headers = await _buildHeaders(getToken);
  try {
    const response = await fetch(`${getApiBaseUrl()}/api/drive/oauth/authorize`, {
      method: "GET",
      headers,
    });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw ApiError.fromResponse(response.status, body);
    }
    return response.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError("network", 0, "Network error.");
  }
}

export async function disconnectOAuth(
  getToken?: TokenGetter,
): Promise<void> {
  const headers = await _buildHeaders(getToken);
  try {
    const response = await fetch(`${getApiBaseUrl()}/api/drive/oauth/disconnect`, {
      method: "DELETE",
      headers,
    });
    if (!response.ok && response.status !== 204) {
      const body = await response.json().catch(() => null);
      throw ApiError.fromResponse(response.status, body);
    }
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError("network", 0, "Network error.");
  }
}

export async function browseDriveFolders(
  parentId: string,
  getToken?: TokenGetter,
): Promise<BrowseFoldersResponse> {
  const headers = await _buildHeaders(getToken);
  try {
    const response = await fetch(
      `${getApiBaseUrl()}/api/drive/browse-folders?parent_id=${encodeURIComponent(parentId)}`,
      { method: "GET", headers },
    );
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw ApiError.fromResponse(response.status, body);
    }
    return response.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError("network", 0, "Network error.");
  }
}

export async function createFolderConnection(
  libraryId: string | null,
  folderId: string,
  folderName: string,
  folderPath: string,
  getToken?: TokenGetter,
): Promise<DriveConnectionResponse> {
  const headers = await _buildHeaders(getToken);
  try {
    const response = await fetch(`${getApiBaseUrl()}/api/drive/folder-connections`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        ...(libraryId ? { library_id: libraryId } : {}),
        folder_id: folderId,
        folder_name: folderName,
        folder_path: folderPath,
      }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw ApiError.fromResponse(response.status, body);
    }
    return response.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError("network", 0, "Network error.");
  }
}

export async function getDriveConnectionProgress(
  connectionId: string,
  getToken?: TokenGetter,
): Promise<DriveSyncProgress> {
  const headers = await _buildHeaders(getToken);
  try {
    const response = await fetch(
      `${getApiBaseUrl()}/api/drive/connections/${connectionId}/progress`,
      { method: "GET", headers },
    );
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw ApiError.fromResponse(response.status, body);
    }
    return response.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError("network", 0, "Network error.");
  }
}

export async function deleteDriveConnection(
  connectionId: string,
  getToken?: TokenGetter,
): Promise<void> {
  const headers = await _buildHeaders(getToken);
  try {
    const response = await fetch(
      `${getApiBaseUrl()}/api/drive/connections/${connectionId}`,
      { method: "DELETE", headers },
    );
    if (!response.ok && response.status !== 204) {
      const body = await response.json().catch(() => null);
      throw ApiError.fromResponse(response.status, body);
    }
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError("network", 0, "Network error.");
  }
}

export async function getWatchedFolders(
  getToken?: TokenGetter,
): Promise<FolderTreeResponse> {
  const headers = await _buildHeaders(getToken);
  try {
    const response = await fetch(`${getApiBaseUrl()}/api/drive/watched-folders`, {
      method: "GET",
      headers,
    });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw ApiError.fromResponse(response.status, body);
    }
    return response.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError("network", 0, "Network error.");
  }
}

export async function enumerateFolders(
  getToken?: TokenGetter,
): Promise<FolderTreeResponse> {
  const headers = await _buildHeaders(getToken);
  try {
    const response = await fetch(
      `${getApiBaseUrl()}/api/drive/watched-folders/enumerate-folders`,
      { method: "POST", headers },
    );
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw ApiError.fromResponse(response.status, body);
    }
    return response.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError("network", 0, "Network error.");
  }
}

export async function toggleFolderSync(
  folderId: string,
  enabled: boolean,
  getToken?: TokenGetter,
): Promise<ToggleFolderResponse> {
  const headers = await _buildHeaders(getToken);
  try {
    const response = await fetch(
      `${getApiBaseUrl()}/api/drive/watched-folders/${folderId}/toggle`,
      {
        method: "PATCH",
        headers,
        body: JSON.stringify({ sync_enabled: enabled }),
      },
    );
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw ApiError.fromResponse(response.status, body);
    }
    return response.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError("network", 0, "Network error.");
  }
}

export async function updateFolderContentTypes(
  folderId: string,
  types: string[],
  getToken?: TokenGetter,
): Promise<WatchedFolder> {
  const headers = await _buildHeaders(getToken);
  try {
    const response = await fetch(
      `${getApiBaseUrl()}/api/drive/watched-folders/${folderId}/content-types`,
      {
        method: "PATCH",
        headers,
        body: JSON.stringify({ content_types: types }),
      },
    );
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw ApiError.fromResponse(response.status, body);
    }
    return response.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError("network", 0, "Network error.");
  }
}

export async function getFolderDisableImpact(
  folderId: string,
  getToken?: TokenGetter,
): Promise<FolderDisableImpact> {
  const headers = await _buildHeaders(getToken);
  try {
    const response = await fetch(
      `${getApiBaseUrl()}/api/drive/watched-folders/${folderId}/impact`,
      { method: "GET", headers },
    );
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw ApiError.fromResponse(response.status, body);
    }
    return response.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError("network", 0, "Network error.");
  }
}
