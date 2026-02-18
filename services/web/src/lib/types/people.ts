export interface PersonResponse {
  person_cluster_id: string;
  label: string | null;
  face_count: number;
  last_seen_scene_time: string | null;
  representative_video_id: string | null;
  representative_scene_id: string | null;
  is_excluded: boolean;
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
