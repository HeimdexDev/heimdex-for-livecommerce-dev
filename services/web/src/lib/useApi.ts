"use client";

import { useCallback } from "react";
import { useAuth } from "./auth";
import {
  search,
  searchScenes as searchScenesApi,
  SearchRequest,
  SearchResponse,
  SceneSearchResponse,
  ApiError,
} from "./api";

/**
 * Hook for making authenticated API calls.
 * 
 * Automatically attaches the auth token when available.
 * Returns loading states and error handling helpers.
 */
export function useApi() {
  const { getAccessToken, isAuthenticated, isLoading: authLoading, login } = useAuth();

  /**
   * Perform a search with automatic auth token attachment.
   */
  const searchWithAuth = useCallback(
    async (request: SearchRequest): Promise<SearchResponse> => {
      return search(request, getAccessToken);
    },
    [getAccessToken]
  );

  const searchScenesWithAuth = useCallback(
    async (request: SearchRequest): Promise<SceneSearchResponse> => {
      return searchScenesApi(request, getAccessToken);
    },
    [getAccessToken]
  );

  /**
   * Check if the error requires re-authentication.
   */
  const isAuthError = useCallback((error: unknown): boolean => {
    return error instanceof ApiError && error.type === "unauthorized";
  }, []);

  /**
   * Check if the error is a forbidden (org mismatch) error.
   */
  const isForbiddenError = useCallback((error: unknown): boolean => {
    return error instanceof ApiError && error.type === "forbidden";
  }, []);

  /**
   * Check if the error is a tenancy error.
   */
  const isTenancyError = useCallback((error: unknown): boolean => {
    return error instanceof ApiError && error.type === "tenancy";
  }, []);

  /**
   * Get a user-friendly error message.
   */
  const getErrorMessage = useCallback((error: unknown): string => {
    if (error instanceof ApiError) {
      return error.detail;
    }
    if (error instanceof Error) {
      return error.message;
    }
    return "An unexpected error occurred";
  }, []);

  /**
   * Handle an API error with appropriate action.
   * Returns true if the error was handled (e.g., redirected to login).
   */
  const handleApiError = useCallback(
    (error: unknown): boolean => {
      if (error instanceof ApiError) {
        if (error.type === "unauthorized") {
          // Trigger login
          login();
          return true;
        }
        // For other errors, return false to let the component handle display
        return false;
      }
      return false;
    },
    [login]
  );

  return {
    search: searchWithAuth,
    searchScenes: searchScenesWithAuth,
    isAuthenticated,
    authLoading,
    isAuthError,
    isForbiddenError,
    isTenancyError,
    getErrorMessage,
    handleApiError,
    login,
  };
}
