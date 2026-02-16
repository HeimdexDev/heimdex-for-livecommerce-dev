"use client";

import { createContext, useContext, useMemo, ReactNode } from "react";
import { ApiClient, createApiClient } from "./client";
import { useAuth } from "@/lib/auth";

const ApiClientContext = createContext<ApiClient | null>(null);

interface ApiClientProviderProps {
  children: ReactNode;
}

export function ApiClientProvider({ children }: ApiClientProviderProps) {
  const { getAccessToken } = useAuth();

  const apiClient = useMemo(() => {
    const baseUrl = process.env.NEXT_PUBLIC_API_URL || "";
    return createApiClient({
      baseUrl,
      getAccessToken,
    });
  }, [getAccessToken]);

  return (
    <ApiClientContext.Provider value={apiClient}>
      {children}
    </ApiClientContext.Provider>
  );
}

export function useApiClient(): ApiClient {
  const client = useContext(ApiClientContext);
  if (!client) {
    throw new Error("useApiClient must be used within ApiClientProvider");
  }
  return client;
}
