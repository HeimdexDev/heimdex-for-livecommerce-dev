// ============================================================================
// Auth Types
// ============================================================================

export interface User {
  email?: string;
  name?: string;
  picture?: string;
  role?: "admin" | "member";
}

export interface AuthContextType {
  isAuthenticated: boolean;
  isLoading: boolean;
  user: User | null;
  error: Error | null;
  login: () => void;
  loginWithCredentials: (email: string, password: string) => Promise<void>;
  logout: () => void;
  getAccessToken: () => Promise<string | null>;
  isAuth0Enabled: boolean;
}
