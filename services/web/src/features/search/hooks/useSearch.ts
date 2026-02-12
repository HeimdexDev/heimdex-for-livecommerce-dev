"use client";

import { useState, useCallback, useEffect } from "react";
import { useAuth, getOrgSlug } from "@/lib/auth";
import { useApi } from "@/lib/useApi";
import {
  SearchFilters,
  AnySearchResponse,
  SceneSearchResponse,
  ApiError,
} from "@/lib/api";
import { User } from "@/lib/types";

export interface SearchError {
  message: string;
  type?: string;
}

export interface UseSearchReturn {
  // State
  alpha: number;
  filters: SearchFilters;
  response: AnySearchResponse | null;
  isLoading: boolean;
  error: SearchError | null;
  lastQuery: string;
  showDebug: boolean;
  orgSlug: string;
  searchMode: string;

  // Auth state
  isAuthenticated: boolean;
  authLoading: boolean;
  user: User | null;
  isAuth0Enabled: boolean;

  // Actions
  setAlpha: (value: number) => void;
  setShowDebug: (value: boolean) => void;
  handleSearch: (query: string) => Promise<void>;
  handleFiltersChange: (newFilters: SearchFilters) => void;
  login: () => void;
  logout: () => void;
}

export function useSearch(): UseSearchReturn {
  const [alpha, setAlpha] = useState(0.5);
  const [filters, setFilters] = useState<SearchFilters>({});
  const [response, setResponse] = useState<AnySearchResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<SearchError | null>(null);
  const [showDebug, setShowDebug] = useState(false);
  const [lastQuery, setLastQuery] = useState("");
  const [orgSlug, setOrgSlug] = useState("");

  const { isAuthenticated, isLoading: authLoading, user, login, logout, isAuth0Enabled } = useAuth();
  const { search, searchScenes } = useApi();
  const searchMode = process.env.NEXT_PUBLIC_SEARCH_MODE || "scenes";

  useEffect(() => {
    setOrgSlug(getOrgSlug());
  }, []);

  const handleSearch = useCallback(
    async (query: string, overrideFilters?: SearchFilters) => {
      const activeFilters = overrideFilters ?? filters;
      setIsLoading(true);
      setError(null);
      setLastQuery(query);

      try {
        let result: AnySearchResponse;
        if (searchMode === "scenes") {
          try {
            const sceneResult: SceneSearchResponse = await searchScenes({ q: query, alpha, filters: activeFilters });
            result = sceneResult;
          } catch (err) {
            if (err instanceof ApiError && err.status === 404) {
              result = await search({ q: query, alpha, filters: activeFilters });
            } else {
              throw err;
            }
          }
        } else {
          result = await search({ q: query, alpha, filters: activeFilters });
        }
        setResponse(result);
      } catch (err) {
        if (err instanceof ApiError) {
          setError({ message: err.detail, type: err.type });
        } else {
          setError({ message: err instanceof Error ? err.message : "Search failed" });
        }
        setResponse(null);
      } finally {
        setIsLoading(false);
      }
    },
    [alpha, filters, search, searchScenes, searchMode]
  );

  const handleFiltersChange = useCallback(
    (newFilters: SearchFilters) => {
      setFilters(newFilters);
      if (lastQuery) {
        handleSearch(lastQuery, newFilters);
      }
    },
    [lastQuery, handleSearch]
  );

  return {
    // State
    alpha,
    filters,
    response,
    isLoading,
    error,
    lastQuery,
    showDebug,
    orgSlug,
    searchMode,

    // Auth state
    isAuthenticated,
    authLoading,
    user,
    isAuth0Enabled,

    // Actions
    setAlpha,
    setShowDebug,
    handleSearch,
    handleFiltersChange,
    login,
    logout,
  };
}
