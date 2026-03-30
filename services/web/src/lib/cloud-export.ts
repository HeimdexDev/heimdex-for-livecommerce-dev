import { getApiBaseUrl } from "./api/utils";

type TokenGetter = () => Promise<string | null>;

export interface CloudExportRequest {
  project_name: string;
  frame_rate: number;
  clips: {
    video_id: string;
    clip_name: string;
    start_ms: number;
    end_ms: number;
  }[];
}

export interface CloudExportResult {
  clip_count: number;
  unresolved_clips: string[];
  filename: string;
}

export async function exportEdlCloud(
  request: CloudExportRequest,
  getToken?: TokenGetter,
): Promise<CloudExportResult> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  if (getToken) {
    try {
      const token = await getToken();
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
    } catch {
      // proceed without auth
    }
  }

  const response = await fetch(`${getApiBaseUrl()}/api/export/edl`, {
    method: "POST",
    headers,
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Export failed (${response.status})`);
  }

  const blob = await response.blob();
  const clipCount = parseInt(response.headers.get("X-Clip-Count") ?? "0", 10);
  const unresolvedRaw = response.headers.get("X-Unresolved-Clips") ?? "";
  const unresolved = unresolvedRaw ? unresolvedRaw.split(",") : [];

  const disposition = response.headers.get("Content-Disposition") ?? "";
  // Prefer RFC 5987 filename* (UTF-8 encoded) over plain filename
  const utf8Match = disposition.match(/filename\*=UTF-8''([^;\s]+)/i);
  const plainMatch = disposition.match(/filename="?([^"]+)"?/);
  const filename = utf8Match
    ? decodeURIComponent(utf8Match[1])
    : (plainMatch?.[1] ?? `${request.project_name}.edl`);

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);

  return {
    clip_count: clipCount,
    unresolved_clips: unresolved,
    filename,
  };
}


export interface CloudClipRequest {
  video_id: string;
  clip_name: string;
  start_ms: number;
  end_ms: number;
}

/**
 * Download a trimmed video clip from a cloud (gd_) video.
 * The server extracts the clip segment using ffmpeg and returns an MP4.
 */
export async function downloadClipCloud(
  request: CloudClipRequest,
  getToken?: TokenGetter,
): Promise<void> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  if (getToken) {
    try {
      const token = await getToken();
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
    } catch {
      // proceed without auth
    }
  }

  const response = await fetch(`${getApiBaseUrl()}/api/export/clip`, {
    method: "POST",
    headers,
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Clip download failed (${response.status})`);
  }

  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const utf8Match = disposition.match(/filename\*=UTF-8''([^;\s]+)/i);
  const plainMatch = disposition.match(/filename="?([^"]+)"?/);
  const filename = utf8Match
    ? decodeURIComponent(utf8Match[1])
    : (plainMatch?.[1] ?? `${request.clip_name || "clip"}.mp4`);

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}


export interface CloudPremiereRequest {
  project_name: string;
  frame_rate: number;
  drive_mount_path: string;
  clips: {
    video_id: string;
    clip_name: string;
    start_ms: number;
    end_ms: number;
  }[];
}

export interface CloudPremiereResult {
  clip_count: number;
  unresolved_clips: string[];
  filename: string;
}

/**
 * Export selected clips as FCP 7 XML for Premiere Pro import.
 * Uses the user's local Google Drive mount path to resolve media file URLs.
 */
export async function exportPremiereCloud(
  request: CloudPremiereRequest,
  getToken?: TokenGetter,
): Promise<CloudPremiereResult> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  if (getToken) {
    try {
      const token = await getToken();
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
    } catch {
      // proceed without auth
    }
  }

  const response = await fetch(`${getApiBaseUrl()}/api/export/premiere`, {
    method: "POST",
    headers,
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Export failed (${response.status})`);
  }

  const blob = await response.blob();
  const clipCount = parseInt(response.headers.get("X-Clip-Count") ?? "0", 10);
  const unresolvedRaw = response.headers.get("X-Unresolved-Clips") ?? "";
  const unresolved = unresolvedRaw ? unresolvedRaw.split(",") : [];

  const disposition = response.headers.get("Content-Disposition") ?? "";
  const utf8Match = disposition.match(/filename\*=UTF-8''([^;\s]+)/i);
  const plainMatch = disposition.match(/filename="?([^"]+)"?/);
  const filename = utf8Match
    ? decodeURIComponent(utf8Match[1])
    : (plainMatch?.[1] ?? `${request.project_name}.xml`);

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);

  return {
    clip_count: clipCount,
    unresolved_clips: unresolved,
    filename,
  };
}


// --- Premiere Package Export (FCPXML 1.8 + ZIP) ---

export interface PremierePackageClipInput {
  scene_id: string;
  video_id: string;
  video_title: string;
  start_ms: number;
  end_ms: number;
  label?: string;
  keyword_tags?: string[];
  transcript_raw?: string;
}

export interface PremierePackageRequest {
  sequence_name: string;
  drive_mount_path: string;
  clips: PremierePackageClipInput[];
  clip_gap_ms: number;
  include_markers: boolean;
  include_transcript_markers: boolean;
}

/**
 * Export selected scenes as an FCPXML 1.8 package (ZIP) for Premiere Pro 2024.
 * The ZIP contains .fcpxml timeline, manifest.json, README.txt, and scenes.csv.
 * Clips reference original media via file:// URLs on the user's Google Drive mount.
 */
export async function exportPremierePackage(
  request: PremierePackageRequest,
  getToken?: TokenGetter,
): Promise<void> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  if (getToken) {
    try {
      const token = await getToken();
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
    } catch {
      // proceed without auth
    }
  }

  const response = await fetch(`${getApiBaseUrl()}/api/export/premiere-package`, {
    method: "POST",
    headers,
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Export failed (${response.status})`);
  }

  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const utf8Match = disposition.match(/filename\*=UTF-8''([^;\s]+)/i);
  const plainMatch = disposition.match(/filename="?([^"]+)"?/);
  const filename = utf8Match
    ? decodeURIComponent(utf8Match[1])
    : (plainMatch?.[1] ?? `${request.sequence_name}_premiere.zip`);

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}


// --- Proxy Pack Export (async via SQS worker) ---

export interface ProxyPackClipInput {
  scene_id: string;
  video_id: string;
  video_title: string;
  start_ms: number;
  end_ms: number;
  label?: string;
  keyword_tags?: string[];
  transcript_raw?: string;
}

export interface ProxyPackRequest {
  sequence_name: string;
  clips: ProxyPackClipInput[];
  clip_gap_ms: number;
  include_markers: boolean;
  include_transcript_markers: boolean;
}

export interface ProxyPackInitResponse {
  job_id: string;
  status: string;
  estimated_size_bytes: number;
  proxy_count: number;
  clip_count: number;
}

export interface ProxyPackStatusResponse {
  job_id: string;
  /** pending | generating | uploading | ready | failed | expired */
  status: string;
  download_url: string | null;
  size_bytes: number | null;
  error: string | null;
  expires_at: string | null;
}

/**
 * Initiate a proxy-pack export job. Returns immediately with a job_id
 * for polling. If a cached export exists, status will be "ready" with
 * the download_url already available.
 */
export async function initiateProxyPack(
  request: ProxyPackRequest,
  getToken?: TokenGetter,
): Promise<ProxyPackInitResponse> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (getToken) {
    try {
      const token = await getToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;
    } catch { /* proceed without auth */ }
  }
  const response = await fetch(`${getApiBaseUrl()}/api/export/proxy-pack`, {
    method: "POST",
    headers,
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Proxy pack initiation failed (${response.status})`);
  }
  return response.json();
}

/**
 * Poll the status of a proxy-pack export job.
 * Terminal states: ready, failed, expired.
 */
export async function pollProxyPackStatus(
  jobId: string,
  getToken?: TokenGetter,
): Promise<ProxyPackStatusResponse> {
  const headers: Record<string, string> = {};
  if (getToken) {
    try {
      const token = await getToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;
    } catch { /* proceed without auth */ }
  }
  const response = await fetch(`${getApiBaseUrl()}/api/export/proxy-pack/${jobId}`, {
    method: "GET",
    headers,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Status check failed (${response.status})`);
  }
  return response.json();
}