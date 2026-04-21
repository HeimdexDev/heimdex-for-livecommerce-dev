// ============================================================================
// Auto-Shorts Types — mirrors app/modules/shorts_auto/schemas.py 1:1.
//
// Kept in lib/types/ (not inside features/shorts-auto/) so other features can
// depend on the request/response shape without reaching across feature
// boundaries. Never add UI-only fields here — put those in
// features/shorts-auto/lib/types.ts.
// ============================================================================

export type ScoringModeRequest = "human" | "product" | "both";

export interface AutoSelectRequest {
  video_id: string;
  mode: ScoringModeRequest;
  person_cluster_id?: string | null;
  count?: number;
  target_duration_sec?: number;
  min_duration_sec?: number;
  prefer_continuous?: boolean;
}

export interface AutoRenderRequest extends AutoSelectRequest {
  title?: string | null;
  auto_caption?: boolean;
}

export interface ClipMemberResponse {
  scene_id: string;
  start_ms: number;
  end_ms: number;
  score: number;
}

export interface AutoClipResponse {
  scene_ids: string[];
  members: ClipMemberResponse[];
  start_ms: number;
  end_ms: number;
  duration_ms: number;
  score: number;
  reasons: string[];
  is_continuous: boolean;
}

/**
 * Every stable value the backend can emit in `skipped_reason`.
 * Extend ``skipReasonCopy`` in the feature's lib/ whenever this grows.
 */
export type AutoSelectSkippedReason =
  | "video_too_short"
  | "no_candidate_scenes_after_filter"
  | "no_scenes_passed_eligibility"
  | "no_clips_met_min_duration";

export interface AutoSelectResponse {
  video_id: string;
  mode: ScoringModeRequest;
  clips: AutoClipResponse[];
  total_duration_ms: number;
  skipped_reason: AutoSelectSkippedReason | string | null;
}
