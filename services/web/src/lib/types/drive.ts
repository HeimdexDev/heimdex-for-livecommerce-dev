export interface DriveStatusResponse {
  connected: boolean;
  connection_status: string | null;
  drive_name: string | null;
  last_sync_at: string | null;
  total_files: number;
  indexed: number;
  processing: number;
  pending: number;
  failed: number;
  last_indexed_at: string | null;
}

export interface DriveFolderInfo {
  folder_path: string;
  file_count: number;
  indexed_count: number;
  processing_count: number;
  failed_count: number;
  pending_count: number;
}

export interface DriveFolderListResponse {
  folders: DriveFolderInfo[];
  total_files: number;
}

export interface DriveConnectionResponse {
  id: string;
  org_id: string;
  library_id: string;
  drive_id: string | null;
  drive_name: string | null;
  scope_type: string;
  folder_id: string | null;
  folder_name: string | null;
  folder_path: string | null;
  status: string;
  last_sync_at: string | null;
  sync_requested_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface SyncTriggerResponse {
  status: string;
  sync_requested_at: string;
}

export interface DriveOAuthStatus {
  connected: boolean;
  google_email: string | null;
  connected_at: string | null;
}

export interface DriveFolderItem {
  id: string;
  name: string;
  parents?: string[];
}

export interface BrowseFoldersResponse {
  folders: DriveFolderItem[];
  parent_id: string;
}
