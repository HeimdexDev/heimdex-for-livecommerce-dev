/**
 * Blur job + layer export API client.
 *
 * Standalone functions matching the shorts-render.ts pattern: every
 * call takes a ``getToken`` callback last, so the hook layer can stay
 * unaware of auth details. Errors are surfaced as thrown ``Error``s
 * with status-aware ``BlurRateLimitError`` / ``BlurDisabledError``
 * subclasses so the UI can distinguish retryable from permanent.
 *
 * Every field here mirrors the pydantic schemas in
 * ``services/api/app/modules/blur/schemas.py``. Keep them in lockstep
 * — this file is the single source of truth on the frontend for
 * blur shape; do NOT scatter duplicate type definitions across hooks.
 */
import { getApiBaseUrl } from "./utils";

type TokenGetter = () => Promise<string | null>;

// ---------- shared types (mirror of the API's pydantic models) ----------

export type BlurCategory =
  | "face"
  | "license_plate"
  | "logo"
  | "card_object"
  | "object";

export type BlurJobStatus =
  | "queued"
  | "running"
  | "done"
  | "failed"
  | "cancelled";

export type BlurJobPhase =
  | "queued"
  | "initializing"
  | "detecting"
  | "encoding"
  | "uploading"
  | "finalizing";

export type BlurExportFormat = "prores_4444";

export interface BlurOptions {
  do_faces?: boolean;
  do_owl?: boolean;
  categories?: BlurCategory[];
  owl_stride?: number;
  owl_score_threshold?: number;
  mosaic_cells?: number;
  feather?: number;
}

export interface BlurJobResponse {
  id: string;
  file_id: string;
  video_id: string;
  requested_by: string;
  status: BlurJobStatus | string;
  options: Record<string, unknown>;
  source_kind: string;
  blurred_s3_key: string | null;
  manifest_s3_key: string | null;
  mask_s3_keys: Record<string, string> | null;
  detections_summary: Record<string, number> | null;
  error: string | null;
  progress_pct: number;
  phase: BlurJobPhase | string | null;
  requested_at: string;
  started_at: string | null;
  completed_at: string | null;

  // Presigned URLs populated only when status=done.
  blurred_playback_url: string | null;
  manifest_url: string | null;
  mask_urls: Record<string, string> | null;
}

export interface BlurJobListResponse {
  items: BlurJobResponse[];
  total: number;
}

export interface BlurExportResponse {
  id: string;
  blur_job_id: string;
  file_id: string;
  video_id: string;
  requested_by: string;
  status: string;
  categories: string[];
  format: string;
  layer_s3_key: string | null;
  error: string | null;
  requested_at: string;
  started_at: string | null;
  completed_at: string | null;
  download_url: string | null;
}

// ---------- error hierarchy ----------

/**
 * Thrown when the API returns 429. The UI should tell the user to
 * wait for existing jobs to finish rather than retry immediately.
 */
export class BlurRateLimitError extends Error {
  readonly isRateLimit = true;
  constructor(message: string) {
    super(message);
    this.name = "BlurRateLimitError";
  }
}

/**
 * Thrown when ``blur_enabled=false`` or ``blur_export_enabled=false``
 * on the target environment. Router returns 404 in those cases — the
 * UI distinguishes this from a real "not found" so it can hide the
 * feature instead of showing an error.
 */
export class BlurDisabledError extends Error {
  readonly isDisabled = true;
  constructor(message: string) {
    super(message);
    this.name = "BlurDisabledError";
  }
}

// ---------- internal helpers ----------

async function authHeaders(getToken: TokenGetter): Promise<Record<string, string>> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  try {
    const token = await getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  } catch {
    /* noop — upstream auth errors surface on the next call */
  }
  return headers;
}

async function handleError(res: Response, hint: string): Promise<never> {
  const body = await res.json().catch(() => ({}));
  const detail = (body as { detail?: string }).detail ?? `${hint} failed (${res.status})`;
  if (res.status === 429) {
    throw new BlurRateLimitError(detail);
  }
  if (res.status === 404 && /disabled/i.test(detail)) {
    throw new BlurDisabledError(detail);
  }
  throw new Error(detail);
}

// ---------- blur job endpoints ----------

/** POST /api/blur/videos/{file_id} — enqueue a new blur job. */
export async function createBlurJob(
  fileId: string,
  options: BlurOptions,
  getToken: TokenGetter,
): Promise<BlurJobResponse> {
  const res = await fetch(`${getApiBaseUrl()}/api/blur/videos/${fileId}`, {
    method: "POST",
    headers: await authHeaders(getToken),
    body: JSON.stringify({ options, source_kind: "proxy" }),
  });
  if (!res.ok) await handleError(res, "blur.createBlurJob");
  return res.json();
}

/** GET /api/blur/videos/{file_id} — list blur jobs for a video. */
export async function listBlurJobsForFile(
  fileId: string,
  getToken: TokenGetter,
): Promise<BlurJobListResponse> {
  const res = await fetch(`${getApiBaseUrl()}/api/blur/videos/${fileId}`, {
    method: "GET",
    headers: await authHeaders(getToken),
  });
  if (!res.ok) await handleError(res, "blur.listBlurJobsForFile");
  return res.json();
}

/** GET /api/blur/jobs/{job_id} — fetch one blur job with presigned URLs. */
export async function getBlurJob(
  jobId: string,
  getToken: TokenGetter,
): Promise<BlurJobResponse> {
  const res = await fetch(`${getApiBaseUrl()}/api/blur/jobs/${jobId}`, {
    method: "GET",
    headers: await authHeaders(getToken),
  });
  if (!res.ok) await handleError(res, "blur.getBlurJob");
  return res.json();
}

// ---------- export endpoints ----------

/** POST /api/blur/jobs/{job_id}/export — create a layer export job. */
export async function createBlurExport(
  jobId: string,
  categories: BlurCategory[],
  format: BlurExportFormat,
  getToken: TokenGetter,
): Promise<BlurExportResponse> {
  const res = await fetch(`${getApiBaseUrl()}/api/blur/jobs/${jobId}/export`, {
    method: "POST",
    headers: await authHeaders(getToken),
    body: JSON.stringify({ categories, format }),
  });
  if (!res.ok) await handleError(res, "blur.createBlurExport");
  return res.json();
}

/** GET /api/blur/exports/{export_id} — fetch export status + download URL. */
export async function getBlurExport(
  exportId: string,
  getToken: TokenGetter,
): Promise<BlurExportResponse> {
  const res = await fetch(`${getApiBaseUrl()}/api/blur/exports/${exportId}`, {
    method: "GET",
    headers: await authHeaders(getToken),
  });
  if (!res.ok) await handleError(res, "blur.getBlurExport");
  return res.json();
}

/**
 * Compute a direct browser download URL for a completed export. The
 * backend endpoint 307-redirects to a fresh presigned URL, so this is
 * safe to use as the ``href`` on a plain ``<a download>`` tag.
 */
export function buildBlurExportDownloadHref(exportId: string): string {
  return `${getApiBaseUrl()}/api/blur/exports/${exportId}/download`;
}
