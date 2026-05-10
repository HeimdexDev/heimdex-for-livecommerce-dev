// ============================================================================
// Shorts auto product mode — wizard request/response types.
//
// Mirrors services/api/app/modules/shorts_auto_product/schemas.py exactly.
// Single source of truth for the wizard feature dir; no other types are
// duplicated locally inside features/shorts-auto-product-wizard/.
//
// NEVER import from features/*. This module is consumed by:
//   - lib/api/shorts-auto-product-wizard.ts (client)
//   - features/shorts-auto-product-wizard/ (consumers)
// ============================================================================

export type ProductDistribution = "single" | "multi";
export type Language = "ko" | "en";
export type ScanIntent = "preview" | "commit";

export type JobKind =
  | "enumeration"
  | "tracking"
  | "scan_order"
  | "render_child";

export type ScanStage =
  | "queued"
  | "enumerating"
  | "enumeration_done"
  | "tracking"
  | "assembling"
  | "rendering"
  | "preview_ready"
  | "fanned_out"
  | "committed"
  | "done"
  | "failed"
  | "cancelled";

export type ScanErrorCode =
  | "internal_error"
  | "tracker_low_confidence_global"
  | "no_products_detected"
  | "render_enqueue_failed"
  | "video_no_longer_available";

// ----------------------------------------------------------------------
// POST /api/shorts/auto/scan-orders/videos/{video_id}
// ----------------------------------------------------------------------

export interface ScanOrderCreateRequest {
  length_seconds: number; // 10..120
  requested_count: number; // 1..50
  time_range_start_ms: number | null;
  time_range_end_ms: number | null;
  product_distribution: ProductDistribution;
  language: Language;
  intent: ScanIntent;
  // Legacy single-pick (PR 1 of multi-product wizard backend). Mutually
  // exclusive with ``catalog_entry_ids``; the server normalizer 422s
  // when both are populated. Kept for back-compat with any external
  // caller; the wizard sends ``catalog_entry_ids`` exclusively.
  catalog_entry_id?: string | null;
  // PR 2 of multi-product wizard: list of catalog entries the user
  // picked at the product-select step. Server validates:
  //   * 1 <= length <= requested_count (when populated)
  //   * each id exists, belongs to (org, video), not soft-rejected
  //   * no duplicates
  // Children get a deterministic round-robin distribution at fan-out:
  // child[i] = sorted(ids)[i % len(ids)]. Empty list = legacy
  // whole-catalog round-robin.
  catalog_entry_ids?: string[];
}

// ----------------------------------------------------------------------
// V1 product catalog endpoints — used by the wizard's product-select
// step to trigger enumeration and poll for the resulting catalog.
// ----------------------------------------------------------------------

/**
 * Body for ``POST /api/shorts/auto/products/{video_id}/scan``.
 * One field — kept compact since the wizard always uses 60s presets;
 * the wizard's wizard-level length_seconds is captured separately on
 * the scan_order.
 */
export interface ProductScanRequest {
  duration_preset_sec: 30 | 60 | 90;
}

/** Response for ``POST /api/shorts/auto/products/{video_id}/scan``. */
export interface ProductScanResponse {
  job_id: string;
  /**
   * True when an in-flight enumerate job already covers this video —
   * the same parent gets returned, no duplicate work / no extra cost.
   */
  deduped: boolean;
}

/** A single enumerated product in the catalog (gallery shape). */
export interface CatalogProductSummary {
  catalog_entry_id: string;
  label: string;
  // v0.16.0: nullable for STT-source rows (no canonical crop because
  // STT enumeration never sees a frame). The wizard renders a
  // generic icon when null. Vision-source rows always have a URL.
  canonical_crop_url: string | null;
  enumeration_confidence: number;
  // v0.16.0: nullable — vision-only metric, NULL for STT-source rows.
  prominence_score: number | null;
  /** True after the user picked this product and tracking ran. */
  has_track_data: boolean;
  /** Populated only AFTER tracking — null during enumeration polling. */
  appearance_count: number | null;
  total_appearance_seconds: number | null;
  // v0.16.0 — STT-first enumeration provenance fields.
  /** ``"vision"`` (default) | ``"stt"`` | ``"stt_xref"`` | ``"manifest"`` | ``"hybrid"``. */
  enumeration_source: string;
  /** First spoken mention timestamp (ms). NULL for vision-source rows. */
  first_mention_ms: number | null;
  /** Verbatim host quote that surfaced this product. NULL for vision rows. */
  example_quote: string | null;
}

/**
 * Lifecycle of the catalog from the user's POV — drives the wizard's
 * polling decisions much more cleanly than guessing from
 * ``products.length``: an empty list with ``scan_status='never'`` means
 * "trigger me", with ``in_progress`` means "still scanning", with
 * ``complete`` means "scan ran but found nothing", with ``failed``
 * means "show the user the failure".
 */
export type ScanStatus = "never" | "in_progress" | "complete" | "failed";

/** Response for ``GET /api/shorts/auto/products/{video_id}``. */
export interface ProductCatalogResponse {
  video_id: string;
  scan_status: ScanStatus;
  scan_job_id: string | null;
  enumeration_version: string | null;
  enumeration_prompt_version: string | null;
  products: CatalogProductSummary[];
}

export interface ScanOrderResponse {
  parent_job_id: string;
  deduped: boolean;
}

// ----------------------------------------------------------------------
// GET /api/shorts/auto/scan-orders/{parent_job_id}
// ----------------------------------------------------------------------

export interface JobStatusResponse {
  job_id: string;
  kind: JobKind;
  stage: ScanStage;
  progress_pct: number;
  progress_label: string | null;
  completed_at: string | null;
  failed_at: string | null;
  cancelled_at: string | null;
  error_code: ScanErrorCode | null;
  error_message: string | null;
  render_job_id: string | null;
  /**
   * Underlying ShortsRenderJob.status for ``render_child`` jobs —
   * used to distinguish "scan finished, render in flight" from
   * "scan finished, render done." Mirror of the backend field
   * added in v0.16.1. Values: ``"queued"`` | ``"rendering"`` |
   * ``"completed"`` | ``"failed"``. ``null`` when ``render_job_id``
   * is null (e.g., scan_order parents) or for backward compat.
   */
  render_status: string | null;
  parent_job_id: string | null;
  shorts_index: number | null;
  cost_usd_estimate: string;
}

export interface ScanOrderStatusResponse {
  parent: JobStatusResponse;
  children: JobStatusResponse[];
  children_complete: number;
  children_failed: number;
  children_total: number;
}

// ----------------------------------------------------------------------
// Stage classification helpers (pure functions — no side effects).
// ----------------------------------------------------------------------

const ACTIVE_STAGES: ReadonlySet<ScanStage> = new Set<ScanStage>([
  "queued",
  "enumerating",
  "enumeration_done",
  "tracking",
  "assembling",
  "rendering",
  "preview_ready",
  "fanned_out",
]);

const TERMINAL_STAGES: ReadonlySet<ScanStage> = new Set<ScanStage>([
  "committed",
  "done",
  "failed",
  "cancelled",
]);

export function isActiveStage(stage: ScanStage): boolean {
  return ACTIVE_STAGES.has(stage);
}

export function isTerminalStage(stage: ScanStage): boolean {
  return TERMINAL_STAGES.has(stage);
}
