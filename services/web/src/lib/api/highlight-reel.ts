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

// Mirror of services/api/app/modules/shorts_render/schemas.py::RenderJobResponse.
// Memory: feedback_frontend_types_mirror_backend_schema.md — adding a field
// here without copying it from schemas.py is a regression vector.
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
  thumbnail_video_id: string | null;
  thumbnail_scene_id: string | null;
  // Refinement chain (migration 056 / PR 5 of whisper subtitles).
  // - replaced_by_render_job_id: forward pointer to a refined child render.
  //   The wizard polls this and follows the chain to swap to the refined
  //   download_url silently.
  // - refined_from_render_job_id: back pointer on a child to its parent.
  // - refinement_source: 'whisper' | 'manual_edit' | null. 'manual_edit'
  //   prevents future automatic refinement passes.
  replaced_by_render_job_id: string | null;
  refined_from_render_job_id: string | null;
  refinement_source: string | null;
}

// Subset of heimdex_media_contracts.composition.SubtitleSpec sent by the
// frontend when an operator edits subtitles. Backend re-validates as the
// full SubtitleSpec — extra fields like ``style`` and ``template_id`` flow
// through unchanged when callers include them.
export interface SubtitleEdit {
  text: string;
  start_ms: number;
  end_ms: number;
  template_id?: string | null;
  style?: Record<string, unknown>;
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

export async function getRenderJobStatus(
  jobId: string,
  getToken: TokenGetter,
): Promise<RenderJobResponse> {
  const headers: Record<string, string> = {};
  try {
    const token = await getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  } catch { /* noop */ }

  const res = await fetch(
    `${getApiBaseUrl()}/api/shorts/render/${jobId}`,
    { method: "GET", headers },
  );

  if (!res.ok) {
    throw new Error(`Status check failed (${res.status})`);
  }

  return res.json();
}

/**
 * Promote a render job's current ``input_spec`` to a fresh queued
 * render (PR 1 of auto-shorts-subtitle-editor plan).
 *
 * Pairs with manual subtitle edits: the operator types in the
 * editor → debounced ``patchRenderJobSubtitles`` saves to
 * ``input_spec.subtitles`` → operator clicks "Render with my edits"
 * → this helper enqueues the new render.
 *
 * Backend endpoint: ``POST /api/shorts/render/{job_id}/rerender``
 * (no body — server reads the parent's current input_spec).
 *
 * Idempotent within a 30s composition-hash window. Returns the
 * newly-created child ``RenderJobResponse`` (or the deduped
 * existing one). Caller should pivot the wizard's polling target
 * to the returned ``id`` so ``useRefinedRenderChain`` follows the
 * fresh render.
 */
export async function rerenderFromEdits(
  jobId: string,
  getToken: TokenGetter,
): Promise<RenderJobResponse> {
  const headers: Record<string, string> = {};
  try {
    const token = await getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  } catch { /* noop */ }

  const res = await fetch(
    `${getApiBaseUrl()}/api/shorts/render/${jobId}/rerender`,
    { method: "POST", headers },
  );

  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `Rerender failed (${res.status})`);
  }

  return res.json();
}

/**
 * Replace a render job's subtitles and lock out automatic Whisper
 * refinement (the API sets ``refinement_source='manual_edit'``).
 *
 * Backend endpoint: ``PATCH /api/shorts/render/{job_id}/subtitles``
 * (PR 5 of the whisper-subtitles plan). Distinct from the title
 * PATCH per CLAUDE.md "single-field schema; do NOT widen".
 *
 * Manual edits are sticky — even if the operator later clears the
 * subtitles, the flag remains so a future Whisper pass doesn't
 * repopulate them. To re-enable automatic refinement, the operator
 * must trigger a fresh render (post creates a new row with a clean
 * ``refinement_source``).
 */
export async function patchRenderJobSubtitles(
  jobId: string,
  subtitles: SubtitleEdit[],
  getToken: TokenGetter,
): Promise<RenderJobResponse> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  try {
    const token = await getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  } catch { /* noop */ }

  const res = await fetch(
    `${getApiBaseUrl()}/api/shorts/render/${jobId}/subtitles`,
    {
      method: "PATCH",
      headers,
      body: JSON.stringify({ subtitles }),
    },
  );

  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `Subtitle update failed (${res.status})`);
  }

  return res.json();
}

/**
 * Subtitle file format the backend exposes via
 * ``GET /api/shorts/render/{job_id}/subtitles.{format}``.
 *
 * SRT covers every NLE + social platform; WebVTT is needed for
 * ``<track>`` injection in custom HTML5 players.
 */
export type SubtitleDownloadFormat = "srt" | "vtt";

export interface SubtitleDownloadResult {
  /** Serialized subtitle file body, ready to write to disk. */
  body: string;
  /**
   * Server-suggested filename. Read from the response's
   * ``Content-Disposition`` header — prefers the RFC 5987
   * ``filename*`` form so Korean titles survive intact, falls
   * back to the ASCII ``filename=`` and finally to a fixed
   * default if the header is malformed.
   */
  filename: string;
}

const _SUBTITLE_DOWNLOAD_DEFAULT_FILENAME: Record<SubtitleDownloadFormat, string> = {
  srt: "subtitles.srt",
  vtt: "subtitles.vtt",
};

/** Pull the best-available filename out of a Content-Disposition header. */
function _parseSubtitleFilename(
  header: string | null,
  format: SubtitleDownloadFormat,
): string {
  const fallback = _SUBTITLE_DOWNLOAD_DEFAULT_FILENAME[format];
  if (!header) return fallback;
  // RFC 5987 form: filename*=UTF-8''<percent-encoded>. Prefer this so
  // Korean titles survive — every modern browser respects it.
  const utf8Match = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch {
      /* fall through to ASCII */
    }
  }
  const asciiMatch = header.match(/filename="([^"]+)"/i);
  if (asciiMatch) return asciiMatch[1];
  return fallback;
}

/**
 * Download the latest saved subtitle list as a serialized
 * file. Reads from ``input_spec.subtitles`` server-side, so the
 * returned body always reflects the most recent
 * ``patchRenderJobSubtitles`` call — no need to re-render before
 * exporting.
 *
 * Returns the raw body + the server-suggested filename. Caller is
 * responsible for triggering the actual save-as dialog (typically
 * via a Blob + anchor click in the component layer) so this helper
 * stays pure for tests.
 */
export async function fetchRenderSubtitles(
  jobId: string,
  format: SubtitleDownloadFormat,
  getToken: TokenGetter,
): Promise<SubtitleDownloadResult> {
  const headers: Record<string, string> = {};
  try {
    const token = await getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  } catch { /* noop */ }

  const res = await fetch(
    `${getApiBaseUrl()}/api/shorts/render/${jobId}/subtitles.${format}`,
    { method: "GET", headers },
  );

  if (!res.ok) {
    let detail: { detail?: string } = {};
    try {
      detail = await res.json();
    } catch {
      /* noop */
    }
    throw new Error(detail.detail || `Subtitle download failed (${res.status})`);
  }

  const body = await res.text();
  const filename = _parseSubtitleFilename(
    res.headers.get("Content-Disposition"),
    format,
  );
  return { body, filename };
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
