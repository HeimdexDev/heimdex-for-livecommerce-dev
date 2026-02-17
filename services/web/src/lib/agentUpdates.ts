/**
 * Agent update manifest client.
 *
 * Fetches the latest agent release manifest from a stable URL and provides
 * typed access to download metadata. All fetching is server-side only —
 * the client page calls our own /api/agent/latest proxy route instead.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AgentDownloadInfo {
  url: string;
  sha256: string;
  size_bytes: number;
}

export interface AgentManifest {
  version: string;
  release_date?: string;
  release_notes?: string;
  downloads: Record<AgentPlatform, AgentDownloadInfo>;
  min_version?: string;
}

/** Sanitised manifest returned to the browser (no internal URLs leaked). */
export interface AgentManifestPublic {
  version: string;
  release_date?: string;
  release_notes?: string;
  platforms: AgentPlatform[];
  downloads: Record<
    AgentPlatform,
    { sha256: string; size_bytes: number }
  >;
}

// ---------------------------------------------------------------------------
// Platform allowlist
// ---------------------------------------------------------------------------

const ALLOWED_PLATFORMS = [
  "darwin-arm64",
  "darwin-amd64",
  "windows-amd64",
] as const;

export type AgentPlatform = (typeof ALLOWED_PLATFORMS)[number];

export function isValidPlatform(value: string): value is AgentPlatform {
  return (ALLOWED_PLATFORMS as readonly string[]).includes(value);
}

export const PLATFORM_LABELS: Record<AgentPlatform, string> = {
  "darwin-arm64": "macOS (Apple Silicon)",
  "darwin-amd64": "macOS (Intel)",
  "windows-amd64": "Windows",
};

// ---------------------------------------------------------------------------
// Manifest URL
// ---------------------------------------------------------------------------

const DEFAULT_MANIFEST_URL =
  "https://updates.heimdex.co/agent/latest.json";

export function getManifestUrl(): string {
  return process.env.AGENT_UPDATE_MANIFEST_URL || DEFAULT_MANIFEST_URL;
}

// ---------------------------------------------------------------------------
// Server-side fetcher (with short cache)
// ---------------------------------------------------------------------------

let cachedManifest: AgentManifest | null = null;
let cachedAt = 0;
const CACHE_TTL_MS = 60_000; // 60 seconds

export async function fetchManifest(): Promise<AgentManifest> {
  const now = Date.now();
  if (cachedManifest && now - cachedAt < CACHE_TTL_MS) {
    return cachedManifest;
  }

  const url = getManifestUrl();
  const res = await fetch(url, {
    next: { revalidate: 60 },
    signal: AbortSignal.timeout(10_000),
  });

  if (!res.ok) {
    throw new Error(
      `Failed to fetch agent manifest: HTTP ${res.status}`,
    );
  }

  const data: unknown = await res.json();
  const manifest = parseManifest(data);

  cachedManifest = manifest;
  cachedAt = now;
  return manifest;
}

/** Reset the in-memory cache (useful for tests). */
export function resetManifestCache(): void {
  cachedManifest = null;
  cachedAt = 0;
}

// ---------------------------------------------------------------------------
// Manifest parsing & validation
// ---------------------------------------------------------------------------

export function parseManifest(data: unknown): AgentManifest {
  if (typeof data !== "object" || data === null) {
    throw new Error("Manifest must be a JSON object");
  }

  const obj = data as Record<string, unknown>;

  if (typeof obj.version !== "string" || !obj.version) {
    throw new Error("Manifest missing required field: version");
  }

  if (typeof obj.downloads !== "object" || obj.downloads === null) {
    throw new Error("Manifest missing required field: downloads");
  }

  const downloads = obj.downloads as Record<string, unknown>;
  const parsed: Partial<Record<AgentPlatform, AgentDownloadInfo>> = {};

  for (const platform of ALLOWED_PLATFORMS) {
    const entry = downloads[platform];
    if (!entry || typeof entry !== "object") continue;

    const e = entry as Record<string, unknown>;
    if (
      typeof e.url !== "string" ||
      typeof e.sha256 !== "string" ||
      typeof e.size_bytes !== "number"
    ) {
      continue;
    }

    parsed[platform] = {
      url: e.url,
      sha256: e.sha256,
      size_bytes: e.size_bytes,
    };
  }

  if (Object.keys(parsed).length === 0) {
    throw new Error("Manifest has no valid download entries");
  }

  return {
    version: obj.version,
    release_date:
      typeof obj.release_date === "string" ? obj.release_date : undefined,
    release_notes:
      typeof obj.release_notes === "string"
        ? obj.release_notes
        : undefined,
    downloads: parsed as Record<AgentPlatform, AgentDownloadInfo>,
    min_version:
      typeof obj.min_version === "string" ? obj.min_version : undefined,
  };
}

// ---------------------------------------------------------------------------
// Public manifest (strips internal download URLs)
// ---------------------------------------------------------------------------

export function toPublicManifest(m: AgentManifest): AgentManifestPublic {
  const platforms = Object.keys(m.downloads) as AgentPlatform[];
  const downloads: Record<string, { sha256: string; size_bytes: number }> =
    {};

  for (const p of platforms) {
    downloads[p] = {
      sha256: m.downloads[p].sha256,
      size_bytes: m.downloads[p].size_bytes,
    };
  }

  return {
    version: m.version,
    release_date: m.release_date,
    release_notes: m.release_notes,
    platforms,
    downloads: downloads as Record<
      AgentPlatform,
      { sha256: string; size_bytes: number }
    >,
  };
}
