const AGENT_BASE = "http://127.0.0.1:8787";
const HEALTH_TIMEOUT_MS = 500;
const STATUS_TIMEOUT_MS = 2000;

export interface AgentHealth {
  status: string;
  version: string;
  uptime_s: number;
  device_id: string;
}

export type AgentJobStatus = "pending" | "running" | "completed" | "failed";
export type AgentJobType = "scan" | "index" | "upload_scenes" | "generate_thumbnails";

export interface AgentJob {
  id: string;
  type: AgentJobType;
  status: AgentJobStatus;
  source_id?: string;
  file_id?: string;
  progress: number;
  error?: string;
  created_at: string;
  updated_at: string;
}

export type AgentState = "idle" | "indexing" | "paused" | "error";

export interface AgentStatus {
  state: AgentState;
  last_error?: string;
  sources_count: number;
  files_count: number;
  jobs_running: number;
  active_job?: AgentJob;
}

export async function checkAgentHealth(): Promise<AgentHealth | null> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), HEALTH_TIMEOUT_MS);
    const res = await fetch(`${AGENT_BASE}/health`, { signal: controller.signal });
    clearTimeout(timeout);
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

/**
 * Fetches agent status including active job progress.
 * Uses /local/status which requires LoopbackGuard only (no auth token).
 * Returns null if agent is unreachable or CORS blocks the request.
 */
export async function getAgentStatus(): Promise<AgentStatus | null> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), STATUS_TIMEOUT_MS);
    const res = await fetch(`${AGENT_BASE}/local/status`, { signal: controller.signal });
    clearTimeout(timeout);
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export function getAgentPlaybackUrl(videoId: string, startMs?: number): string {
  const base = `${AGENT_BASE}/playback/file?file_id=${encodeURIComponent(videoId)}`;
  if (startMs != null && startMs > 0) {
    return `${base}#t=${(startMs / 1000).toFixed(1)}`;
  }
  return base;
}

export function getAgentThumbnailUrl(videoId: string, sceneId?: string): string {
  const base = `${AGENT_BASE}/playback/thumbnail?file_id=${encodeURIComponent(videoId)}`;
  if (sceneId) {
    return `${base}&scene_id=${encodeURIComponent(sceneId)}`;
  }
  return base;
}

export function getAgentClipUrl(videoId: string, startMs: number, endMs: number, name?: string): string {
  const base = `${AGENT_BASE}/export/clip?file_id=${encodeURIComponent(videoId)}&start_ms=${startMs}&end_ms=${endMs}`;
  if (name) {
    return `${base}&name=${encodeURIComponent(name)}`;
  }
  return base;
}

export function getCloudPlaybackUrl(videoId: string, startMs?: number): string {
  const base = `/api/playback/${encodeURIComponent(videoId)}`;
  if (startMs != null && startMs > 0) {
    return `${base}#t=${(startMs / 1000).toFixed(1)}`;
  }
  return base;
}

export function getCloudThumbnailUrl(videoId: string, sceneId: string): string {
  return `/api/thumbnails/${encodeURIComponent(videoId)}/${encodeURIComponent(sceneId)}`;
}

export function getFaceThumbnailUrl(personClusterId: string, cacheBuster?: number): string {
  const suffix = cacheBuster != null ? `?v=${cacheBuster}` : "";
  return `/api/thumbnails/faces/${encodeURIComponent(personClusterId)}${suffix}`;
}

export interface AgentSource {
  id: string;
  type: string;
  path: string;
  display_name: string;
  drive_nickname?: string;
  present: boolean;
  files_count: number;
  created_at: string;
}

export async function getAgentSources(): Promise<AgentSource[]> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), STATUS_TIMEOUT_MS);
    const res = await fetch(`${AGENT_BASE}/local/sources`, { signal: controller.signal });
    clearTimeout(timeout);
    if (!res.ok) return [];
    const data = await res.json();
    return data.sources ?? [];
  } catch {
    return [];
  }
}

export async function deleteAgentSource(id: string): Promise<boolean> {
  try {
    const res = await fetch(`${AGENT_BASE}/local/sources/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
    return res.status === 204;
  } catch {
    return false;
  }
}

export async function renameAgentSource(id: string, displayName: string): Promise<boolean> {
  try {
    const res = await fetch(`${AGENT_BASE}/local/sources/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ display_name: displayName }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function pickDirectory(): Promise<string | null> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), PICK_FOLDER_TIMEOUT_MS);
  try {
    const res = await fetch(`${AGENT_BASE}/local/pick-directory`, {
      method: "POST",
      signal: controller.signal,
    });
    clearTimeout(timeout);

    if (res.status === 204) return null;
    if (res.status === 409) throw new Error("폴더 선택 창이 이미 열려있습니다.");

    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new Error(body?.error ?? `Agent error (${res.status})`);
    }

    const data: { path: string } = await res.json();
    return data.path;
  } catch (error) {
    clearTimeout(timeout);
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error("폴더 선택 요청 시간이 초과되었습니다.");
    }
    throw error;
  }
}

export interface PickFolderResult {
  source_id: string;
  path: string;
  display_name: string;
}

const PICK_FOLDER_TIMEOUT_MS = 120_000;

/**
 * Asks the agent to open a native folder picker dialog.
 * Returns the added source on success, null if the user cancelled.
 * Throws on network / agent errors.
 */
export async function pickFolder(): Promise<PickFolderResult | null> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), PICK_FOLDER_TIMEOUT_MS);
  try {
    const res = await fetch(`${AGENT_BASE}/local/pick-folder`, {
      method: "POST",
      signal: controller.signal,
    });
    clearTimeout(timeout);

    if (res.status === 204) return null;
    if (res.status === 409) throw new Error("폴더 선택 창이 이미 열려있습니다.");

    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new Error(body?.error ?? `Agent error (${res.status})`);
    }

    return res.json();
  } catch (error) {
    clearTimeout(timeout);
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error("폴더 선택 요청 시간이 초과되었습니다.");
    }
    throw error;
  }
}
