/**
 * Resolve the API base URL dynamically.
 *
 * Priority:
 *  1. NEXT_PUBLIC_API_URL env var (if non-empty) — used in local dev
 *  2. window.location.origin (browser) — production/staging multi-subdomain
 *  3. "" (SSR fallback, currently unused — all callers are "use client")
 */
const _ENV_API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";
export function getApiBaseUrl(): string {
  if (_ENV_API_URL) return _ENV_API_URL;
  if (typeof window !== "undefined") return window.location.origin;
  return "";
}

const AUTH0_ENABLED = process.env.NEXT_PUBLIC_AUTH0_ENABLED === "true";

export function formatTimestamp(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
  }
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

export function formatDuration(startMs: number, endMs: number): string {
  return `${formatTimestamp(startMs)} - ${formatTimestamp(endMs)}`;
}

export function isAuthRequired(): boolean {
  return AUTH0_ENABLED;
}
