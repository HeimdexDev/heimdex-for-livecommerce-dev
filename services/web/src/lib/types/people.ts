export interface PersonResponse {
  person_cluster_id: string;
  label: string | null;
  face_count: number;
  last_seen_scene_time: string | null;
  representative_video_id: string | null;
  representative_scene_id: string | null;
  is_excluded: boolean;
  matched_video_titles?: string[] | null;
}

export interface PeopleListResponse {
  people: PersonResponse[];
  total: number;
}

export interface RenamePersonResponse {
  person_cluster_id: string;
  label: string | null;
}

export interface PersonVideoItem {
  video_id: string;
  video_title: string | null;
  scene_count: number;
}

export interface PersonVideosResponse {
  person_cluster_id: string;
  videos: PersonVideoItem[];
  total: number;
}

export interface ExcludePreferencesResponse {
  excluded_person_cluster_ids: string[];
}

export interface VideoExclusionsResponse {
  person_cluster_id: string;
  excluded_video_ids: string[];
}

export interface PersonTimelineScene {
  scene_id: string;
  start_ms: number;
  end_ms: number;
  has_person: boolean;
}

export interface PersonTimelineVideo {
  video_id: string;
  video_title: string | null;
  total_scenes: number;
  scenes: PersonTimelineScene[];
}

export interface PersonTimelineResponse {
  person_cluster_id: string;
  videos: PersonTimelineVideo[];
}

export interface MergePersonRequest {
  source_cluster_ids: string[];
  target_cluster_id: string;
  keep_label?: string | null;
}

export interface MergePersonResponse {
  target_cluster_id: string;
  merged_source_ids: string[];
  scenes_updated: number;
  label: string | null;
}

export interface BulkDeleteRequest {
  person_cluster_ids: string[];
}

export interface BulkDeleteResponse {
  deleted_ids: string[];
  failed_ids: string[];
  total_deleted: number;
}