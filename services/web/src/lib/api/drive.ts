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

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

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
    const response = await fetch(`${API_BASE_URL}/api/drive/status`, {
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
    const response = await fetch(`${API_BASE_URL}/api/drive/connections`, {
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
      `${API_BASE_URL}/api/drive/connections/${connectionId}/sync`,
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
      `${API_BASE_URL}/api/drive/connections/${connectionId}/folders`,
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
    const response = await fetch(`${API_BASE_URL}/api/drive/oauth/status`, {
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
    const response = await fetch(`${API_BASE_URL}/api/drive/oauth/authorize`, {
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
    const response = await fetch(`${API_BASE_URL}/api/drive/oauth/disconnect`, {
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
      `${API_BASE_URL}/api/drive/browse-folders?parent_id=${encodeURIComponent(parentId)}`,
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
    const response = await fetch(`${API_BASE_URL}/api/drive/folder-connections`, {
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
      `${API_BASE_URL}/api/drive/connections/${connectionId}/progress`,
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
      `${API_BASE_URL}/api/drive/connections/${connectionId}`,
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
