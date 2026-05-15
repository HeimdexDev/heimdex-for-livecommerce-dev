"use client";

import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import { getOrgSettings, updateOrgSettings, OrgSettingsResponse } from "@/lib/api/orgSettings";

const DEFAULT_SETTINGS: OrgSettingsResponse = {
  thumbnail_aspect_ratio: "16:9",
};

interface OrgSettingsContextType {
  settings: OrgSettingsResponse;
  isLoading: boolean;
  updateThumbnailAspectRatio: (ratio: "16:9" | "9:16") => Promise<void>;
}

const OrgSettingsContext = createContext<OrgSettingsContextType | null>(null);

export function OrgSettingsProvider({ children }: { children: ReactNode }) {
  const { getAccessToken, isAuthenticated } = useAuth();
  const [settings, setSettings] = useState<OrgSettingsResponse>(DEFAULT_SETTINGS);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (!isAuthenticated) {
      setIsLoading(false);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const result = await getOrgSettings(getAccessToken);
        if (!cancelled) setSettings(result);
      } catch (err) {
        console.warn("[Heimdex] Failed to fetch org settings:", err);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [isAuthenticated, getAccessToken]);

  const updateThumbnailAspectRatio = useCallback(async (ratio: "16:9" | "9:16") => {
    const updated = await updateOrgSettings({ thumbnail_aspect_ratio: ratio }, getAccessToken);
    setSettings(updated);
  }, [getAccessToken]);

  return (
    <OrgSettingsContext.Provider value={{ settings, isLoading, updateThumbnailAspectRatio }}>
      {children}
    </OrgSettingsContext.Provider>
  );
}

export function useOrgSettings(): OrgSettingsContextType {
  const context = useContext(OrgSettingsContext);
  if (!context) {
    throw new Error("useOrgSettings must be used within OrgSettingsProvider");
  }
  return context;
}
