// ============================================================================
// Auth Types
// ============================================================================

export interface User {
  email?: string;
  name?: string;
  picture?: string;
}

export interface AuthContextType {
  isAuthenticated: boolean;
  isLoading: boolean;
  user: User | null;
  error: Error | null;
  login: () => void;
  logout: () => void;
  getAccessToken: () => Promise<string | null>;
  isAuth0Enabled: boolean;
}
