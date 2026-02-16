export interface PersonSummary {
  person_cluster_id: string;
  label: string | null;
  face_count: number;
  last_seen_scene_time: string | null;
}

export interface PeopleListResponse {
  people: PersonSummary[];
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
