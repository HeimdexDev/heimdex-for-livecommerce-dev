import type { ExportPremiereRequest, ExportPremiereResponse } from "@/lib/types";

const AGENT_BASE = "http://127.0.0.1:8787";
const EXPORT_TIMEOUT_MS = 30_000;
const OPEN_PREMIERE_TIMEOUT_MS = 120_000;
const PREMIERE_INFO_TIMEOUT_MS = 2_000;

export async function exportToPremiere(
  request: ExportPremiereRequest,
): Promise<ExportPremiereResponse> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), EXPORT_TIMEOUT_MS);
    const response = await fetch(`${AGENT_BASE}/export/premiere`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
      signal: controller.signal,
    });
    clearTimeout(timeout);

    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new Error(body?.error || `Export failed with status ${response.status}`);
    }

    return response.json();
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error("Export request timed out");
    }
    throw error;
  }
}

// --- Open in Premiere Pro (via Heimdex Agent) ---

export interface PremiereInfoResponse {
  installed: boolean;
  app_path?: string;
  version?: string;
  export_dir?: string;
  last_project_path?: string;
  google_drive_mounts?: string[];
}

export interface OpenPremiereResponse {
  status: string;
  export_path?: string;
  premiere?: string;
  project_path?: string;
  error?: string;
}

/**
 * Check if Premiere Pro is installed and get agent export configuration.
 * Returns null if the agent is not running.
 */
export async function getPremiereInfo(): Promise<PremiereInfoResponse | null> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), PREMIERE_INFO_TIMEOUT_MS);
    const response = await fetch(`${AGENT_BASE}/local/premiere-info`, {
      signal: controller.signal,
    });
    clearTimeout(timeout);

    if (!response.ok) return null;
    return response.json();
  } catch {
    return null;
  }
}

/**
 * Tell the Heimdex Agent to download a Premiere package and open it.
 * Timeout is long (120s) to cover folder picker + download + launch.
 */
export async function openInPremiere(
  downloadUrl: string,
  filename: string,
  openProject: boolean = true,
): Promise<OpenPremiereResponse> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), OPEN_PREMIERE_TIMEOUT_MS);
    const response = await fetch(`${AGENT_BASE}/local/open-premiere`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ download_url: downloadUrl, filename, open_project: openProject }),
      signal: controller.signal,
    });
    clearTimeout(timeout);

    const body = await response.json();

    if (!response.ok) {
      return {
        status: "error",
        error: body?.error || `Failed with status ${response.status}`,
        export_path: body?.export_path,
      };
    }

    return body;
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      return { status: "error", error: "요청 시간이 초과되었습니다" };
    }
    return {
      status: "error",
      error: error instanceof Error ? error.message : "Agent 연결에 실패했습니다",
    };
  }
}
