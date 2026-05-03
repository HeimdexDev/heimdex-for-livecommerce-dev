// ============================================================================
// Shorts auto product wizard API client.
//
// Mirrors lib/api/shorts-auto.ts style: plain fetch + getApiBaseUrl, Bearer
// token via TokenGetter, custom error subclasses so the UI can branch on
// `err.isRateLimit` / `err.isFeatureDisabled` / `err.isValidation` without
// parsing strings.
//
// NEVER import from features/*. This module is the one-way public surface
// the wizard feature dir consumes.
// ============================================================================

import type {
  ProductCatalogResponse,
  ProductScanRequest,
  ProductScanResponse,
  ScanOrderCreateRequest,
  ScanOrderResponse,
  ScanOrderStatusResponse,
} from "../types/shorts-auto-product-wizard";
import { getApiBaseUrl } from "./utils";

type TokenGetter = () => Promise<string | null>;

// Error subclasses follow the shorts-auto.ts convention so the wizard's
// error-handling code can mirror existing patterns.

export class WizardRateLimitError extends Error {
  readonly isRateLimit = true;
  constructor(message: string) {
    super(message);
    this.name = "WizardRateLimitError";
  }
}

export class WizardFeatureDisabledError extends Error {
  readonly isFeatureDisabled = true;
  constructor(message: string) {
    super(message);
    this.name = "WizardFeatureDisabledError";
  }
}

export class WizardBudgetExceededError extends Error {
  readonly isBudgetExceeded = true;
  constructor(message: string) {
    super(message);
    this.name = "WizardBudgetExceededError";
  }
}

export class WizardValidationError extends Error {
  readonly isValidation = true;
  constructor(message: string) {
    super(message);
    this.name = "WizardValidationError";
  }
}

async function authHeader(tokenGetter: TokenGetter): Promise<HeadersInit> {
  const token = await tokenGetter();
  return token
    ? { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }
    : { "Content-Type": "application/json" };
}

/**
 * Read the API's `detail` field from a 422 (validation) response. Backend
 * already writes user-appropriate copy (e.g., "requested_count *
 * length_seconds must be <= 1800s"), so the UI surfaces it verbatim.
 */
async function detailMessage(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    return JSON.stringify(body.detail ?? body);
  } catch {
    return res.statusText || `HTTP ${res.status}`;
  }
}

// ----------------------------------------------------------------------
// POST /api/shorts/auto/scan-orders/videos/{video_id}
// ----------------------------------------------------------------------

export async function createScanOrder(
  videoId: string,
  body: ScanOrderCreateRequest,
  tokenGetter: TokenGetter,
): Promise<ScanOrderResponse> {
  const res = await fetch(
    `${getApiBaseUrl()}/api/shorts/auto/scan-orders/videos/${encodeURIComponent(videoId)}`,
    {
      method: "POST",
      credentials: "include",
      headers: await authHeader(tokenGetter),
      body: JSON.stringify(body),
    },
  );
  if (res.status === 404) {
    throw new WizardFeatureDisabledError(
      "Wizard is not enabled for this org",
    );
  }
  if (res.status === 402) {
    throw new WizardBudgetExceededError(await detailMessage(res));
  }
  if (res.status === 422) {
    throw new WizardValidationError(await detailMessage(res));
  }
  if (res.status === 429) {
    throw new WizardRateLimitError(await detailMessage(res));
  }
  if (!res.ok) {
    throw new Error(`createScanOrder failed: ${await detailMessage(res)}`);
  }
  return (await res.json()) as ScanOrderResponse;
}

// ----------------------------------------------------------------------
// GET /api/shorts/auto/scan-orders/{parent_job_id}
// ----------------------------------------------------------------------

export async function getScanOrderStatus(
  parentJobId: string,
  tokenGetter: TokenGetter,
): Promise<ScanOrderStatusResponse> {
  const res = await fetch(
    `${getApiBaseUrl()}/api/shorts/auto/scan-orders/${encodeURIComponent(parentJobId)}`,
    {
      method: "GET",
      credentials: "include",
      headers: await authHeader(tokenGetter),
    },
  );
  if (res.status === 404) {
    throw new WizardFeatureDisabledError(
      "Scan order not found or wizard disabled",
    );
  }
  if (!res.ok) {
    throw new Error(`getScanOrderStatus failed: ${await detailMessage(res)}`);
  }
  return (await res.json()) as ScanOrderStatusResponse;
}

// ----------------------------------------------------------------------
// POST /api/shorts/auto/scan-orders/{parent_job_id}/cancel
// ----------------------------------------------------------------------

export async function cancelScanOrder(
  parentJobId: string,
  tokenGetter: TokenGetter,
): Promise<void> {
  const res = await fetch(
    `${getApiBaseUrl()}/api/shorts/auto/scan-orders/${encodeURIComponent(parentJobId)}/cancel`,
    {
      method: "POST",
      credentials: "include",
      headers: await authHeader(tokenGetter),
    },
  );
  if (res.status === 404) {
    // Already terminal or missing — treat as success (no info leak).
    return;
  }
  if (!res.ok) {
    throw new Error(`cancelScanOrder failed: ${await detailMessage(res)}`);
  }
}

// ----------------------------------------------------------------------
// POST /api/shorts/auto/products/{video_id}/scan
//
// V1 enumeration trigger — wizard's product-select step calls this on
// mount. Idempotent: an in-flight enumeration returns the same job id
// with deduped=true (no duplicate cost). Frontend ignores the job id
// and just polls getProductCatalog for the resulting entries.
// ----------------------------------------------------------------------

export async function triggerEnumeration(
  videoId: string,
  body: ProductScanRequest,
  tokenGetter: TokenGetter,
): Promise<ProductScanResponse> {
  const res = await fetch(
    `${getApiBaseUrl()}/api/shorts/auto/products/${encodeURIComponent(videoId)}/scan`,
    {
      method: "POST",
      credentials: "include",
      headers: await authHeader(tokenGetter),
      body: JSON.stringify(body),
    },
  );
  if (res.status === 404) {
    throw new WizardFeatureDisabledError(
      "Product mode v2 is not enabled for this org",
    );
  }
  if (res.status === 402) {
    throw new WizardBudgetExceededError(await detailMessage(res));
  }
  if (res.status === 429) {
    throw new WizardRateLimitError(await detailMessage(res));
  }
  if (!res.ok) {
    throw new Error(`triggerEnumeration failed: ${await detailMessage(res)}`);
  }
  return (await res.json()) as ProductScanResponse;
}

// ----------------------------------------------------------------------
// GET /api/shorts/auto/products/{video_id}
//
// Polled every 5s by the product-select step. Returns the active
// catalog (non-rejected entries). Empty entries[] means enumeration
// is still in flight (or genuinely found no products — caller
// distinguishes via a max-poll-duration timeout).
// ----------------------------------------------------------------------

export async function getProductCatalog(
  videoId: string,
  tokenGetter: TokenGetter,
): Promise<ProductCatalogResponse> {
  const res = await fetch(
    `${getApiBaseUrl()}/api/shorts/auto/products/${encodeURIComponent(videoId)}`,
    {
      method: "GET",
      credentials: "include",
      headers: await authHeader(tokenGetter),
    },
  );
  if (res.status === 404) {
    throw new WizardFeatureDisabledError(
      "Product mode v2 is not enabled for this org",
    );
  }
  if (!res.ok) {
    throw new Error(`getProductCatalog failed: ${await detailMessage(res)}`);
  }
  return (await res.json()) as ProductCatalogResponse;
}
