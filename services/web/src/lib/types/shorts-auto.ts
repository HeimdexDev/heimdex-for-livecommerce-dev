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
  /**
   * Optional explicit scene_ids to render as the short. When set,
   * backend skips auto-select and composes exactly these scenes in
   * order. Used by the per-clip render buttons so the user picks
   * which of the previewed clips actually gets rendered.
   * Omit to render the top-scoring clip from a fresh auto-select.
   */
  scene_ids?: string[] | null;
}

export interface ClipMemberResponse {
  scene_id: string;
  start_ms: number;
  end_ms: number;
  score: number;
  /**
   * Speaker-diarized transcript for this scene when available, falling
   * back to ``transcript_norm`` then ``transcript_raw`` server-side.
   * Whitespace-only strings collapse to ``null``. Used by the
   * inspector script panel without a per-scene fetch.
   */
  transcript?: string | null;
  /**
   * Vision-captioned scene description, surfaced as a fallback when no
   * transcript exists. ``null`` when the source ``scene_caption`` is
   * empty or whitespace-only.
   */
  scene_caption?: string | null;
}

/**
 * Which scene-selection path actually produced the clips.
 * - "pure": deterministic heuristic scorer (always available)
 * - "llm":  OpenAI-based scorer (gated by AUTO_SHORTS_LLM_ENABLED + rollout)
 * Surfaced so the UI can show an "AI selected" badge and subtly explain
 * when the LLM path fell back to pure on an error.
 */
export type AutoShortsScorer = "pure" | "llm";

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
  /**
   * Which scorer actually produced ``clips``. Defaults to "pure" for
   * backward compat with older backends — required-but-optional in TS
   * so a stale server doesn't break the type contract.
   */
  scorer?: AutoShortsScorer;
}

/**
 * Shape returned by GET /api/shorts/auto-availability.
 * ``llm_enabled`` is only true when the master LLM flag is on AND
 * rollout_pct > 0, so a 0% rollout correctly hides the AI toggle.
 */
export interface AutoShortsAvailability {
  enabled: boolean;
  llm_enabled: boolean;
}
