/**
 * API client for /api/shorts/presets — subtitle preset CRUD.
 *
 * Backed by services/api/app/modules/subtitle_presets/. Org + user scope is
 * enforced server-side via Auth0 + tenancy middleware; this client only
 * handles auth header injection and JSON shape.
 *
 * Wire types live in features/shorts-editor/lib/overlay-types.ts so the
 * editor and the API client share a single TypeScript mirror of contracts.
 */

import type {
  PresetKind,
  WirePreset,
  WirePresetListResponse,
} from "@/features/shorts-editor/lib/overlay-types";
import { getApiBaseUrl } from "./utils";

type TokenGetter = () => Promise<string | null>;

export class PresetRateLimitError extends Error {
  readonly isRateLimit = true;
  constructor(message: string) {
    super(message);
    this.name = "PresetRateLimitError";
  }
}

async function authHeaders(getToken: TokenGetter): Promise<Record<string, string>> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  try {
    const token = await getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  } catch {
    /* noop — calling code can ride out the 401 if there's no token */
  }
  return headers;
}

async function handleResponse<T>(res: Response, action: string): Promise<T> {
  if (res.status === 429) {
    throw new PresetRateLimitError(
      `${action} 빈도 제한에 도달했습니다. 잠시 후 다시 시도해주세요.`,
    );
  }
  if (!res.ok) {
    let detail = `${action} failed: HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* response wasn't JSON — keep the default detail */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// CRUD
// ---------------------------------------------------------------------------

export async function listPresets(
  args: { kind?: PresetKind; limit?: number; offset?: number },
  getToken: TokenGetter,
): Promise<WirePresetListResponse> {
  const params = new URLSearchParams();
  if (args.kind) params.set("kind", args.kind);
  if (args.limit != null) params.set("limit", String(args.limit));
  if (args.offset != null) params.set("offset", String(args.offset));
  const url = `${getApiBaseUrl()}/api/shorts/presets${
    params.size > 0 ? `?${params.toString()}` : ""
  }`;
  const res = await fetch(url, {
    method: "GET",
    headers: await authHeaders(getToken),
  });
  return handleResponse<WirePresetListResponse>(res, "프리셋 조회");
}

export async function createPreset(
  body: {
    name: string;
    kind: PresetKind;
    style_json: Record<string, unknown>;
    is_shared: boolean;
  },
  getToken: TokenGetter,
): Promise<WirePreset> {
  const res = await fetch(`${getApiBaseUrl()}/api/shorts/presets`, {
    method: "POST",
    headers: await authHeaders(getToken),
    body: JSON.stringify(body),
  });
  return handleResponse<WirePreset>(res, "프리셋 저장");
}

export async function updatePreset(
  presetId: string,
  body: {
    name?: string;
    style_json?: Record<string, unknown>;
    is_shared?: boolean;
  },
  getToken: TokenGetter,
): Promise<WirePreset> {
  const res = await fetch(`${getApiBaseUrl()}/api/shorts/presets/${presetId}`, {
    method: "PATCH",
    headers: await authHeaders(getToken),
    body: JSON.stringify(body),
  });
  return handleResponse<WirePreset>(res, "프리셋 수정");
}

export async function deletePreset(
  presetId: string,
  getToken: TokenGetter,
): Promise<void> {
  const res = await fetch(`${getApiBaseUrl()}/api/shorts/presets/${presetId}`, {
    method: "DELETE",
    headers: await authHeaders(getToken),
  });
  if (res.status === 204) return;
  await handleResponse<unknown>(res, "프리셋 삭제");
}
