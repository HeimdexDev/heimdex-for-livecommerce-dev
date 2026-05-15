import { getApiBaseUrl } from "./utils";
import type { RenderJobResponse } from "./highlight-reel";

export type { RenderJobResponse };

type TokenGetter = () => Promise<string | null>;

export interface RenderJobListResponse {
  items: RenderJobResponse[];
  total: number;
}

/**
 * Thrown when the backend returns 429 Too Many Requests on
 * POST /api/shorts/render. The UI should surface this as a "wait a
 * moment" message distinct from a generic submission failure so the
 * user understands retrying immediately won't help.
 */
export class RenderRateLimitError extends Error {
  readonly isRateLimit = true;
  constructor(message: string) {
    super(message);
    this.name = "RenderRateLimitError";
  }
}

export interface CompositionResponse {
  composition: Record<string, unknown>;
  source: "render_job" | "generated";
}

/**
 * Mirror of services/api/app/modules/shorts_render/schemas.py::ShortsSummaryResponse.
 * Returned by POST /api/shorts/render/{job_id}/summary. The summary is
 * also persisted on the render row (migration 059), so a subsequent
 * GET /api/shorts/render carries it on RenderJobResponse.summary —
 * the endpoint is a generate/regenerate trigger, not the read path.
 */
export interface ShortsSummaryResponse {
  render_job_id: string;
  summary: string;
  prompt_version: string;
  model: string;
  cost_usd: number;
  generated_at: string;
}

async function authHeaders(getToken: TokenGetter): Promise<Record<string, string>> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  try {
    const token = await getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  } catch { /* noop */ }
  return headers;
}

export async function submitRender(
  composition: Record<string, unknown>,
  videoId: string,
  title: string | null,
  getToken: TokenGetter,
): Promise<RenderJobResponse> {
  const headers = await authHeaders(getToken);
  const res = await fetch(`${getApiBaseUrl()}/api/shorts/render`, {
    method: "POST",
    headers,
    body: JSON.stringify({ video_id: videoId, title, composition }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    const message = detail.detail || `Render submission failed (${res.status})`;
    if (res.status === 429) {
      throw new RenderRateLimitError(message);
    }
    throw new Error(message);
  }
  return res.json();
}

export async function listRenderJobs(
  getToken: TokenGetter,
  limit = 20,
  offset = 0,
): Promise<RenderJobListResponse> {
  const headers = await authHeaders(getToken);
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  const res = await fetch(`${getApiBaseUrl()}/api/shorts/render?${params}`, {
    method: "GET",
    headers,
  });
  if (!res.ok) {
    throw new Error(`Failed to list render jobs (${res.status})`);
  }
  return res.json();
}

/**
 * Fetch a single render job by id. Backend ``GET /api/shorts/render/{job_id}``
 * returns ``RenderJobResponse`` including the (presigned, expiring)
 * ``download_url`` for the rendered MP4. Owner-scoped on the server.
 */
export async function getRenderJob(
  jobId: string,
  getToken: TokenGetter,
): Promise<RenderJobResponse> {
  const headers = await authHeaders(getToken);
  const res = await fetch(`${getApiBaseUrl()}/api/shorts/render/${jobId}`, {
    method: "GET",
    headers,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `Failed to get render job (${res.status})`);
  }
  return res.json();
}

export async function getShortComposition(
  shortId: string,
  getToken: TokenGetter,
): Promise<CompositionResponse> {
  const headers = await authHeaders(getToken);
  const res = await fetch(`${getApiBaseUrl()}/api/shorts/${shortId}/composition`, {
    method: "GET",
    headers,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `Failed to get composition (${res.status})`);
  }
  return res.json();
}

/**
 * Rename a render job. Backend ``PATCH /api/shorts/render/{job_id}``
 * accepts ``{ title: string | null }`` and returns the updated
 * ``RenderJobResponse``. Owner-scoped on the server: 404 is surfaced
 * for both "not found" and "not yours" so the FE doesn't have to
 * special-case the distinction. ``null`` clears the title.
 */
export async function updateRenderJobTitle(
  jobId: string,
  title: string | null,
  getToken: TokenGetter,
): Promise<RenderJobResponse> {
  const headers = await authHeaders(getToken);
  const res = await fetch(`${getApiBaseUrl()}/api/shorts/render/${jobId}`, {
    method: "PATCH",
    headers,
    body: JSON.stringify({ title }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `Failed to update title (${res.status})`);
  }
  return res.json();
}

/**
 * Delete a render job (DB row + S3 output). Backend returns 204 on
 * success and 404 when the job is missing or not owned by the caller —
 * we treat 404 as a no-op success since the user-visible effect (job
 * gone from their list) is the same.
 */
export async function deleteRenderJob(
  jobId: string,
  getToken: TokenGetter,
): Promise<void> {
  const headers: Record<string, string> = {};
  try {
    const token = await getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  } catch { /* noop */ }

  const res = await fetch(`${getApiBaseUrl()}/api/shorts/render/${jobId}`, {
    method: "DELETE",
    headers,
  });
  if (!res.ok && res.status !== 204 && res.status !== 404) {
    throw new Error(`Failed to delete render job (${res.status})`);
  }
}

/**
 * Generate (or regenerate) the per-short Korean summary for a
 * completed render. Backend ``POST /api/shorts/render/{job_id}/summary``
 * runs a text-only gpt-4o-mini call over the source video's scene
 * signals, persists the result onto the render row (migration 059),
 * and returns it. Owner-scoped on the server.
 *
 * Errors surfaced as a generic ``Error`` with the backend detail:
 *   - 404 — job not found / not owned, or no scene signals available
 *   - 409 — render not yet completed
 *   - 503 — feature flag off, or the OpenAI call failed
 * The caller (saved-shorts card) shows a short failure label and
 * keeps the 요약 생성 button so the operator can retry.
 */
export async function generateRenderJobSummary(
  jobId: string,
  getToken: TokenGetter,
  maxSentences?: number,
): Promise<ShortsSummaryResponse> {
  const headers = await authHeaders(getToken);
  const body =
    maxSentences != null
      ? JSON.stringify({ max_sentences: maxSentences })
      : undefined;
  const res = await fetch(
    `${getApiBaseUrl()}/api/shorts/render/${jobId}/summary`,
    { method: "POST", headers, body },
  );
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(
      detail.detail || `Failed to generate summary (${res.status})`,
    );
  }
  return res.json();
}

/**
 * Download a completed render's MP4 as a blob and trigger a browser
 * download. Returns the filename the browser saved as so callers can
 * surface it in toast notifications.
 */
export async function downloadRenderJob(
  jobId: string,
  filename: string,
  getToken: TokenGetter,
): Promise<string> {
  const headers: Record<string, string> = {};
  try {
    const token = await getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  } catch { /* noop */ }

  const res = await fetch(`${getApiBaseUrl()}/api/shorts/render/${jobId}/download`, {
    method: "GET",
    headers,
  });
  if (!res.ok) {
    throw new Error(`Failed to download render (${res.status})`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const safeName = filename.endsWith(".mp4") ? filename : `${filename}.mp4`;
  const a = document.createElement("a");
  a.href = url;
  a.download = safeName;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  return safeName;
}
