"use client";

import { useDevices } from "../hooks/useDevices";
import { PairingCodeModal } from "./PairingCodeModal";

export function DevicesSettings() {
  const {
    devices,
    isLoading,
    error,
    pairingCode,
    isGenerating,
    generatePairingCode,
    clearPairingCode,
  } = useDevices();

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Devices</h2>
          <p className="text-sm text-gray-500 mt-1">
            Manage registered agent devices and generate pairing codes.
          </p>
        </div>
        <button
          type="button"
          className="btn-primary"
          onClick={generatePairingCode}
          disabled={isGenerating}
        >
          {isGenerating ? "Generating..." : "Generate Pairing Code"}
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
          {error}
        </div>
      )}

      {isLoading ? (
        <div className="text-center py-12 text-gray-500">Loading devices...</div>
      ) : devices.length === 0 ? (
        <div className="card text-center py-12">
          <p className="text-gray-500">No devices registered yet.</p>
          <p className="text-sm text-gray-400 mt-1">
            Generate a pairing code to connect an agent device.
          </p>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 bg-gray-50">
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  Device Name
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  Device ID
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  Status
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  Last Seen
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  Registered
                </th>
              </tr>
            </thead>
            <tbody>
              {devices.map((device) => (
                <tr
                  key={device.device_id}
                  className="border-b border-gray-100 last:border-0"
                >
                  <td className="px-4 py-3 font-medium text-gray-900">
                    {device.device_name}
                  </td>
                  <td className="px-4 py-3 text-gray-500 font-mono text-xs">
                    {device.device_public_id}
                  </td>
                  <td className="px-4 py-3">
                    {device.is_revoked ? (
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-700">
                        Revoked
                      </span>
                    ) : (
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-700">
                        Active
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-500">
                    {device.last_seen_at
                      ? new Date(device.last_seen_at).toLocaleString()
                      : "Never"}
                  </td>
                  <td className="px-4 py-3 text-gray-500">
                    {new Date(device.created_at).toLocaleDateString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {pairingCode && (
        <PairingCodeModal
          isOpen={true}
          onClose={clearPairingCode}
          code={pairingCode.code}
          expiresAt={pairingCode.expires_at}
        />
      )}
    </div>
  );
}
