"use client";

import { useState, useCallback } from "react";
import { useAuth } from "@/lib/auth";
import { createFolderIntent } from "@/lib/api/agent-intents";
import type { AgentIntentResponse } from "@/lib/types";
import { ApiError } from "@/lib/types";

export interface UseAddFolderReturn {
  intentResponse: AgentIntentResponse | null;
  isCreating: boolean;
  error: string | null;
  createIntent: (deviceId: string) => Promise<void>;
  clearIntent: () => void;
}

export function useAddFolder(): UseAddFolderReturn {
  const { getAccessToken } = useAuth();

  const [intentResponse, setIntentResponse] = useState<AgentIntentResponse | null>(
    null,
  );
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const createIntent = useCallback(
    async (deviceId: string) => {
      setIsCreating(true);
      setError(null);
      try {
        const response = await createFolderIntent(getAccessToken, deviceId);
        setIntentResponse(response);
      } catch (err) {
        if (err instanceof ApiError) {
          if (err.status === 429) {
            setError("Too many requests. Please wait and try again.");
          } else if (err.status === 403) {
            setError("You need admin access to add folders.");
          } else if (err.status === 503) {
            setError(
              "Add Folder is temporarily unavailable. Database migrations may be pending. Contact your admin.",
            );
          } else {
            setError(err.detail);
          }
        } else {
          setError("Failed to create folder intent.");
        }
      } finally {
        setIsCreating(false);
      }
    },
    [getAccessToken],
  );

  const clearIntent = useCallback(() => {
    setIntentResponse(null);
    setError(null);
  }, []);

  return {
    intentResponse,
    isCreating,
    error,
    createIntent,
    clearIntent,
  };
}
