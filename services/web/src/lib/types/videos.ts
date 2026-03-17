// ============================================================================
// Video Visibility Types
// ============================================================================

export interface VideoSummary {
  video_id: string;
  video_title: string | null;
  library_id: string | null;
  library_name: string | null;
  source_type: "gdrive" | "removable_disk" | "local" | "youtube" | null;
  scene_count: number;
  first_scene_start_ms: number;
  last_scene_end_ms: number;
  earliest_ingest_time: string | null;
  latest_ingest_time: string | null;
  capture_time: string | null;
  keyword_tags: string[];
  product_tags: string[];
  people_count: number;
  required_drive_nickname: string | null;
  source_path: string | null;
  first_scene_keyframe_ms: number;
  web_view_link?: string | null;
  content_type?: "video" | "image";
}

export interface VideoFacetItem {
  id: string;
  name: string | null;
  count: number;
}

export interface VideoFacets {
  libraries: VideoFacetItem[];
  source_types: VideoFacetItem[];
}

export interface VideoListResponse {
  videos: VideoSummary[];
  total: number;
  next_cursor: string | null;
  facets: VideoFacets;
}

export interface VideoScene {
  scene_id: string;
  start_ms: number;
  end_ms: number;
  transcript_raw: string;
  transcript_char_count: number;
  scene_caption?: string;
  keyword_tags: string[];
  product_tags: string[];
  product_entities: string[];
  speech_segment_count: number;
  speaker_transcript?: string;
  speaker_count?: number;
  ocr_text_raw?: string;
  ocr_char_count?: number;
  people_cluster_ids: string[];
  ingest_time: string | null;
  keyframe_timestamp_ms: number;
}

export interface VideoScenesResponse {
  video_id: string;
  video_title: string | null;
  source_type: string | null;
  source_path: string | null;
  library_name: string | null;
  capture_time: string | null;
  earliest_ingest_time: string | null;
  web_view_link?: string | null;
  scenes: VideoScene[];
  total: number;
}

export interface VideoStats {
  total_videos: number;
  total_scenes: number;
  total_libraries: number;
  source_breakdown: Record<string, number>;
  latest_ingest_time: string | null;
  latest_capture_time: string | null;
  scenes_last_24h: number;
  scenes_last_7d: number;
}

export interface VideoFilters {
  library_id?: string;
  source_type?: "gdrive" | "removable_disk" | "local" | "youtube";
  source_types?: ("gdrive" | "removable_disk" | "local" | "youtube")[];
  content_types?: ("video" | "image")[];
  date_from?: string;
  date_to?: string;
  sort?: "latest" | "alpha_asc" | "alpha_desc";
  page_size?: number;
  after?: string;
}

export interface ReprocessParams {
  min_scene_duration_ms: number;
  max_scene_duration_ms: number;
  threshold: number;
}

export interface ReprocessJobResponse {
  job_id: string;
  video_id: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  scene_params: ReprocessParams;
  scene_count: number | null;
  error: string | null;
  created_at: string;
}

// ============================================================================
// Scene Grouping Types
// ============================================================================

export interface SceneGroup {
  group_index: number;
  start_ms: number;
  end_ms: number;
  scene_count: number;
  representative_scene_id: string;
  scenes: VideoScene[];
}

export interface SceneGroupsResponse {
  video_id: string;
  total_groups: number;
  total_scenes: number;
  groups: SceneGroup[];
}
