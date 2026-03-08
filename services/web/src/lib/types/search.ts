// ============================================================================
// Search Types
// ============================================================================

export interface SearchFilters {
  date_from?: string;
  date_to?: string;
  content_types?: ("video" | "image")[];
  source_types?: ("gdrive" | "removable_disk" | "local" | "youtube")[];
  library_ids?: string[];
  person_cluster_ids?: string[];
  person_cluster_ids_not_in?: string[];
  keyword_tags_in?: string[];
  keyword_tags_not_in?: string[];
  product_tags_in?: string[];
  product_tags_not_in?: string[];
  product_entities_in?: string[];
  product_entities_not_in?: string[];
}

// Mirrors backend validation: max 50 items/list, 64 chars/item
export const TAG_FILTER_MAX_ITEMS = 50;
export const TAG_FILTER_MAX_ITEM_LEN = 64;

export const TAG_FILTER_FIELDS = [
  "keyword_tags_in",
  "keyword_tags_not_in",
  "product_tags_in",
  "product_tags_not_in",
  "product_entities_in",
  "product_entities_not_in",
] as const;

export type TagFilterField = (typeof TAG_FILTER_FIELDS)[number];

export function sanitizeTag(raw: string): string {
  return raw.trim().slice(0, TAG_FILTER_MAX_ITEM_LEN);
}

export function hasTagFilters(filters: SearchFilters): boolean {
  return TAG_FILTER_FIELDS.some(
    (f) => (filters[f]?.length ?? 0) > 0,
  );
}

export type SearchMode = "metadata" | "lexical" | "semantic";

export interface SearchRequest {
  q: string;
  alpha: number;
  filters: SearchFilters;
  include_ocr?: boolean;
  group_by?: "video" | "scene";
  search_mode?: SearchMode;
}

export interface DebugInfo {
  lexical_rank: number | null;
  lexical_score: number | null;
  vector_rank: number | null;
  vector_score: number | null;
  lexical_contribution: number;
  vector_contribution: number;
  ocr_contribution: number;
  fused_score: number;
  quality_factor: number;
  adjusted_score: number;
  diversification_penalty: boolean;
}

export interface SegmentResult {
  segment_id: string;
  video_id: string;
  video_title: string | null;
  library_id: string;
  library_name: string;
  start_ms: number;
  end_ms: number;
  snippet: string;
  thumbnail_url: string | null;
  keyframe_timestamp_ms: number;
  source_type: "gdrive" | "removable_disk" | "local" | "youtube";
  web_view_link?: string | null;
  required_drive_nickname: string | null;
  capture_time: string | null;
  people_cluster_ids: string[];
  debug: DebugInfo;
}

export interface SceneResult {
  scene_id: string;
  video_id: string;
  video_title: string | null;
  library_id: string;
  library_name: string;
  start_ms: number;
  end_ms: number;
  snippet: string;
  ocr_snippet?: string;
  ocr_char_count?: number;
  scene_caption?: string;
  thumbnail_url: string | null;
  source_type: "gdrive" | "removable_disk" | "local" | "youtube";
  web_view_link?: string | null;
  required_drive_nickname: string | null;
  capture_time: string | null;
  people_cluster_ids: string[];
  speech_segment_count: number;
  speaker_transcript?: string;
  speaker_count?: number;
  keyframe_timestamp_ms: number;
  content_type?: "video" | "image";
  image_width?: number;
  image_height?: number;
  image_orientation?: "landscape" | "portrait" | "square";
  debug: DebugInfo;
}

export interface FacetItem {
  value: string;
  count: number;
  label: string | null;
}

export interface Facets {
  libraries: FacetItem[];
  source_types: FacetItem[];
  people_cluster_ids: FacetItem[];
  content_types: FacetItem[];
}

export interface SearchResponse {
  results: SegmentResult[];
  total_candidates: number;
  facets: Facets;
  query: string;
  alpha: number;
  result_type?: "segment";
}

export interface SceneSearchResponse {
  results: SceneResult[];
  total_candidates: number;
  facets: Facets;
  query: string;
  alpha: number;
  result_type: "scene";
}

export interface VideoResult {
  video_id: string;
  video_title: string | null;
  library_id: string;
  library_name: string;
  source_type: "gdrive" | "removable_disk" | "local" | "youtube";
  web_view_link?: string | null;
  matching_scene_count: number;
  best_scene: SceneResult;
  score: number;
}

export interface VideoSearchResponse {
  results: VideoResult[];
  total_candidates: number;
  facets: Facets;
  query: string;
  alpha: number;
  result_type: "video";
}

export type AnySearchResponse = SearchResponse | SceneSearchResponse | VideoSearchResponse;
