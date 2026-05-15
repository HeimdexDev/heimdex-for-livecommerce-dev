// ============================================================================
// Shorts Plan Types
// ============================================================================

export interface ShortsPlanRequest {
  target_count?: number;
  min_duration_ms?: number;
  max_duration_ms?: number;
  weights?: {
    transcript_density?: number;
    visual_change_rate?: number;
    product_mention_boost?: number;
    people_presence_boost?: number;
  };
}

export interface ShortsCandidateResponse {
  candidate_id: string;
  video_id: string;
  scene_ids: string[];
  start_ms: number;
  end_ms: number;
  title_suggestion: string;
  reason: string;
  score: number;
  tags: string[];
  product_refs: string[];
  people_refs: string[];
  transcript_snippet: string;
}

export interface ShortsPlanResponse {
  video_id: string;
  video_title: string | null;
  total_scenes: number;
  eligible_scenes: number;
  candidates: ShortsCandidateResponse[];
}

// ============================================================================
// Export Types
// ============================================================================

export interface ExportClipInput {
  video_id: string;
  scene_id: string;
  clip_name: string;
  start_ms: number;
  end_ms: number;
}

export interface ExportPremiereRequest {
  project_name: string;
  format: "edl";
  frame_rate: number;
  output_dir: string;
  clips: ExportClipInput[];
}

export interface ExportPremiereResponse {
  status: "ok";
  format: "edl";
  output_path: string;
  clip_count: number;
  unresolved_clips: string[];
}
