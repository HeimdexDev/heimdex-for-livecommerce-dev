"use client";

import { useState, useMemo } from "react";
import { useAddFolder } from "../hooks/useAddFolder";
import { AddFolderModal } from "./AddFolderModal";
import type { DeviceListItem } from "@/lib/types";

interface AddFolderButtonProps {
  devices: DeviceListItem[];
}

export function AddFolderButton({ devices }: AddFolderButtonProps) {
  const { intentResponse, isCreating, error, createIntent, clearIntent } =
    useAddFolder();
  const [selectedDeviceId, setSelectedDeviceId] = useState<string>("");

  const activeDevices = useMemo(
    () => devices.filter((d) => !d.is_revoked),
    [devices],
  );

  const handleClick = async () => {
    const deviceId =
      activeDevices.length === 1 ? activeDevices[0].device_id : selectedDeviceId;

    if (!deviceId) return;
    await createIntent(deviceId);
  };

  if (activeDevices.length === 0) {
    return null;
  }

  const needsSelector = activeDevices.length > 1;
  const canCreate =
    !isCreating && (activeDevices.length === 1 || selectedDeviceId !== "");

  return (
    <>
      <div className="flex items-center gap-2">
        {needsSelector && (
          <select
            value={selectedDeviceId}
            onChange={(e) => setSelectedDeviceId(e.target.value)}
            className="text-sm border border-gray-200 rounded-lg px-3 py-2 text-gray-700 bg-white focus:outline-none focus:ring-2 focus:ring-primary-500"
            disabled={isCreating}
          >
            <option value="">Select device...</option>
            {activeDevices.map((d) => (
              <option key={d.device_id} value={d.device_id}>
                {d.device_name}
              </option>
            ))}
          </select>
        )}
        <button
          type="button"
          className="btn-primary"
          onClick={handleClick}
          disabled={!canCreate}
        >
          {isCreating ? "Creating..." : "Add Folder"}
        </button>
      </div>

      {error && !intentResponse && (
        <div className="mt-2 text-sm text-red-600">{error}</div>
      )}

      {intentResponse && (
        <AddFolderModal
          isOpen={true}
          onClose={clearIntent}
          deepLinkUrl={intentResponse.deep_link_url}
          expiresAt={intentResponse.expires_at}
        />
      )}
    </>
  );
}
