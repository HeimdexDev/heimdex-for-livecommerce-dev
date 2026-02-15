"use client";

import { useState, useEffect, useCallback } from "react";
import { useAuth } from "@/lib/auth";
import { getDevices, createPairingCode } from "@/lib/api/devices";
import type { DeviceListItem, PairingCodeResponse } from "@/lib/types";
import { ApiError } from "@/lib/types";

export interface UseDevicesReturn {
  devices: DeviceListItem[];
  isLoading: boolean;
  error: string | null;
  pairingCode: PairingCodeResponse | null;
  isGenerating: boolean;
  fetchDevices: () => Promise<void>;
  generatePairingCode: () => Promise<void>;
  clearPairingCode: () => void;
}

export function useDevices(): UseDevicesReturn {
  const { getAccessToken } = useAuth();

  const [devices, setDevices] = useState<DeviceListItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pairingCode, setPairingCode] = useState<PairingCodeResponse | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);

  const fetchDeviceList = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await getDevices(getAccessToken);
      setDevices(response.devices);
    } catch (err) {
      const msg = err instanceof ApiError ? err.detail : "Failed to load devices";
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }, [getAccessToken]);

  const generateCode = useCallback(async () => {
    setIsGenerating(true);
    setError(null);
    try {
      const response = await createPairingCode(getAccessToken);
      setPairingCode(response);
    } catch (err) {
      const msg = err instanceof ApiError ? err.detail : "Failed to generate pairing code";
      setError(msg);
    } finally {
      setIsGenerating(false);
    }
  }, [getAccessToken]);

  const clearPairingCode = useCallback(() => {
    setPairingCode(null);
  }, []);

  useEffect(() => {
    fetchDeviceList();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return {
    devices,
    isLoading,
    error,
    pairingCode,
    isGenerating,
    fetchDevices: fetchDeviceList,
    generatePairingCode: generateCode,
    clearPairingCode,
  };
}
