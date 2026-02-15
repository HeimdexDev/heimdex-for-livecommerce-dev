// API Client (React Context-based)
export { createApiClient } from "./client";
export type { ApiClient, ApiClientConfig } from "./client";
export { ApiClientProvider, useApiClient } from "./ApiClientProvider";

// Search functions (standalone, for backward compatibility)
export { search, searchUnauthenticated, searchScenes } from "./search";

// Video functions (standalone)
export { getVideos, getVideoScenes, getVideoStats } from "./videos";

export { generateShortsPlan } from "./shorts";

export { getDevices, createPairingCode } from "./devices";

// Utilities
export { formatTimestamp, formatDuration, isAuthRequired } from "./utils";

// Re-export types for convenience
export type {
  ApiErrorType,
  SearchFilters,
  SearchRequest,
  SearchResponse,
  SceneResult,
  SceneSearchResponse,
  AnySearchResponse,
  SegmentResult,
  Facets,
  FacetItem,
  DebugInfo,
  VideoSummary,
  VideoFacetItem,
  VideoFacets,
  VideoListResponse,
  VideoScene,
  VideoScenesResponse,
  VideoStats,
  VideoFilters,
} from "@/lib/types";
export { ApiError } from "@/lib/types";
