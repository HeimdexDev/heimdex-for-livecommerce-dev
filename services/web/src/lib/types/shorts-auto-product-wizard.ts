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
