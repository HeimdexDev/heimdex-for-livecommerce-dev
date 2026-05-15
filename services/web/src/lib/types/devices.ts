export interface DeviceListItem {
  device_id: string;
  device_public_id: string;
  device_name: string;
  is_revoked: boolean;
  last_seen_at: string | null;
  created_at: string;
}

export interface DeviceListResponse {
  devices: DeviceListItem[];
  is_admin: boolean;
}

export interface PairingCodeResponse {
  code: string;
  expires_at: string;
}
