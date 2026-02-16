import type { ExportPremiereRequest, ExportPremiereResponse } from "@/lib/types";

const AGENT_BASE = "http://127.0.0.1:8787";
const EXPORT_TIMEOUT_MS = 30_000;

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
