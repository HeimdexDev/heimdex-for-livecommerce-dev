const AGENT_BASE = "http://127.0.0.1:8787";
const HEALTH_TIMEOUT_MS = 500;

export interface AgentHealth {
  status: string;
  version: string;
  uptime_s: number;
  device_id: string;
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
