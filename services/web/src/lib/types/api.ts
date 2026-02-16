// ============================================================================
// API Error Types
// ============================================================================

export type ApiErrorType = 
  | "unauthorized"      // 401 - Not authenticated
  | "forbidden"         // 403 - Not allowed in this org
  | "tenancy"           // 400 - Invalid hostname/tenancy
  | "not_found"         // 404 - Resource not found
  | "server_error"      // 5xx - Server error
  | "network"           // Network/fetch error
  | "unknown";          // Unknown error

export class ApiError extends Error {
  type: ApiErrorType;
  status: number;
  detail: string;

  constructor(type: ApiErrorType, status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.type = type;
    this.status = status;
    this.detail = detail;
  }

  static fromResponse(status: number, body: { detail?: string } | null): ApiError {
    const detail = body?.detail || `Request failed with status ${status}`;
    
    if (status === 401) {
      return new ApiError("unauthorized", status, "Session expired. Please login again.");
    }
    if (status === 403) {
      return new ApiError("forbidden", status, "You don't have access to this organization.");
    }
    if (status === 400 && detail.toLowerCase().includes("tenancy")) {
      return new ApiError("tenancy", status, "Invalid organization hostname. Check your URL.");
    }
    if (status === 400 && detail.toLowerCase().includes("subdomain")) {
      return new ApiError("tenancy", status, "Invalid organization hostname. Check your URL.");
    }
    if (status === 404) {
      return new ApiError("not_found", status, detail);
    }
    if (status >= 500) {
      return new ApiError("server_error", status, "Server error. Please try again later.");
    }
    
    return new ApiError("unknown", status, detail);
  }
}
