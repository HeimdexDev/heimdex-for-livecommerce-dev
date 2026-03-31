import { getApiBaseUrl } from "./utils";

type TokenGetter = () => Promise<string | null>;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface HighlightClipPreview {
  video_id: string;
  video_title: string | null;
  scene_id: string;
  start_ms: number;
  end_ms: number;
  timeline_start_ms: number;
  duration_ms: number;
  run_scene_count: number;
}

export interface HighlightReelPreviewResponse {
  person_cluster_id: string;
  clips: HighlightClipPreview[];
  total_duration_ms: number;
  videos_used: number;
  videos_available: number;
  videos_excluded: number;
}

export interface RenderJobResponse {
  id: string;
  video_id: string;
  title: string | null;
  status: string;
  created_at: string;
  completed_at: string | null;
  render_time_ms: number | null;
  output_duration_ms: number | null;
  output_size_bytes: number | null;
  error: string | null;
  download_url: string | null;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

export async function generateHighlightPreview(
  personClusterId: string,
  targetDurationS: number,
  getToken: TokenGetter,
): Promise<HighlightReelPreviewResponse> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  try {
    const token = await getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  } catch { /* noop */ }

  const res = await fetch(
    `${getApiBaseUrl()}/api/people/${personClusterId}/highlight-reel/preview`,
    {
      method: "POST",
      headers,
      body: JSON.stringify({ target_duration_s: targetDurationS }),
    },
  );

  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `Preview failed (${res.status})`);
  }

  return res.json();
}

export async function submitHighlightRender(
  personClusterId: string,
  clips: HighlightClipPreview[],
  title: string | null,
  getToken: TokenGetter,
): Promise<RenderJobResponse> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  try {
    const token = await getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  } catch { /* noop */ }

  const res = await fetch(
    `${getApiBaseUrl()}/api/people/${personClusterId}/highlight-reel/render`,
    {
      method: "POST",
      headers,
      body: JSON.stringify({ clips, title }),
    },
  );

  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `Render failed (${res.status})`);
  }

  return res.json();
}
