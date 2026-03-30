"use client";

import { Auth0Provider, useAuth0 } from "@auth0/auth0-react";
import { createContext, useContext, useCallback, useState, useEffect, ReactNode } from "react";
import { AuthContextType, User } from "./types";

// Environment variables for Auth0 configuration
const AUTH0_ENABLED = process.env.NEXT_PUBLIC_AUTH0_ENABLED === "true";
const AUTH0_DOMAIN = process.env.NEXT_PUBLIC_AUTH0_DOMAIN || "";
const AUTH0_CLIENT_ID = process.env.NEXT_PUBLIC_AUTH0_CLIENT_ID || "";
const AUTH0_AUDIENCE = process.env.NEXT_PUBLIC_AUTH0_AUDIENCE || "";
// Auth0 organization is resolved dynamically from the subdomain via
// /api/auth/org-info. Falls back to NEXT_PUBLIC_AUTH0_ORGANIZATION env var
// during SSR or if the API call fails.
const AUTH0_ORGANIZATION_FALLBACK = process.env.NEXT_PUBLIC_AUTH0_ORGANIZATION || "";

function getInitialAuth0Org(): string {
  if (typeof window === "undefined") return AUTH0_ORGANIZATION_FALLBACK;
  // Invitation URL has organization= param — use it directly
  const params = new URLSearchParams(window.location.search);
  const orgParam = params.get("organization");
  if (orgParam) return orgParam;
  return AUTH0_ORGANIZATION_FALLBACK;
}

// Mutable — updated after /api/auth/org-info fetch completes
let _resolvedAuth0Org = getInitialAuth0Org();
let _orgInfoFetched = false;

async function fetchAuth0OrgId(): Promise<string> {
  if (_orgInfoFetched) return _resolvedAuth0Org;
  try {
    // Always use relative URL — must resolve from the current subdomain's
    // Host header, not NEXT_PUBLIC_API_URL (which may be hardcoded to a
    // specific subdomain like livenow.app.heimdex.co).
    const resp = await fetch("/api/auth/org-info");
    if (resp.ok) {
      const data = await resp.json();
      if (data.auth0_org_id) {
        _resolvedAuth0Org = data.auth0_org_id;
      }
    }
  } catch {
    // Fallback to env var
  }
  _orgInfoFetched = true;
  return _resolvedAuth0Org;
}

const AUTH0_ORGANIZATION = getInitialAuth0Org();

// Validate Auth0 configuration
if (AUTH0_ENABLED && (!AUTH0_DOMAIN || !AUTH0_CLIENT_ID)) {
  console.error(
    "[Heimdex] Auth0 is enabled but NEXT_PUBLIC_AUTH0_DOMAIN or NEXT_PUBLIC_AUTH0_CLIENT_ID is not set."
  );
}

const AuthContext = createContext<AuthContextType | null>(null);

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}

export function getOrgSlug(): string {
  if (typeof window === "undefined") return "";
  const hostname = window.location.hostname;
  const match = hostname.match(
    /^([^.]+)\.app\.(?:heimdex(?:demo)?\.(?:co|local|dev)|heimdexdemo\.dev)/
  );
  return match ? match[1] : hostname;
}

// Dev mode auth provider (when Auth0 is disabled)
function DevAuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  // Check for stored dev token on mount
  useEffect(() => {
    const storedToken = sessionStorage.getItem("heimdex_dev_token");
    if (storedToken) {
      setToken(storedToken);
    }
    setIsLoading(false);
  }, []);

  const login = useCallback(() => {
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
  }, []);

  const loginWithCredentials = useCallback(async (email: string, password: string) => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || window.location.origin;

    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch(`${apiUrl}/api/auth/dev-login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        const err = new Error(errorData.detail || `Login failed: ${response.status}`);
        setError(err);
        throw err;
      }

      const data = await response.json();
      setToken(data.access_token);
      sessionStorage.setItem("heimdex_dev_token", data.access_token);
    } catch (err) {
      const error = err instanceof Error ? err : new Error("Login failed");
      setError(error);
      throw error;
    } finally {
      setIsLoading(false);
    }
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    sessionStorage.removeItem("heimdex_dev_token");
  }, []);

  const getAccessToken = useCallback(async () => {
    return token;
  }, [token]);

  // Parse user info from JWT token (simple decode, not validation)
  const user = token ? parseJwtUser(token) : null;

  const value: AuthContextType = {
    isAuthenticated: !!token,
    isLoading,
    user,
    error,
    login,
    loginWithCredentials,
    logout,
    getAccessToken,
    isAuth0Enabled: false,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// Parse user info from dev JWT (not for security, just display)
function parseJwtUser(token: string): User | null {
  try {
    const base64Url = token.split(".")[1];
    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const payload = JSON.parse(atob(base64));
    return {
      email: payload.email,
      name: payload.email?.split("@")[0],
      role: payload.role === "admin" ? "admin" : "member",
    };
  } catch {
    return null;
  }
}

// Auth0 mode auth provider
function Auth0AuthProvider({ children }: { children: ReactNode }) {
  const {
    isAuthenticated,
    isLoading,
    user,
    error,
    loginWithRedirect,
    logout: auth0Logout,
    getAccessTokenSilently,
  } = useAuth0();

  // Fetch authoritative role from backend database (not Auth0 token)
  const [dbRole, setDbRole] = useState<"admin" | "member">("member");

  useEffect(() => {
    if (!isAuthenticated || isLoading) return;
    (async () => {
      try {
        // Don't pass organization to getAccessTokenSilently — the token
        // already has the org from the login flow. Passing a mismatched
        // org here causes silent failures.
        const token = await getAccessTokenSilently({
          authorizationParams: {
            audience: AUTH0_AUDIENCE,
          },
        });
        const res = await fetch("/api/auth/me", {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.ok) {
          const data = await res.json();
          console.info("[Heimdex] /api/auth/me role:", data.role);
          setDbRole(data.role === "admin" ? "admin" : "member");
        } else {
          console.warn("[Heimdex] /api/auth/me failed:", res.status, res.statusText);
        }
      } catch (err) {
        console.error("[Heimdex] Failed to fetch user role:", err);
      }
    })();
  }, [isAuthenticated, isLoading, getAccessTokenSilently]);

  const login = useCallback(async () => {
    await fetchAuth0OrgId();
    loginWithRedirect({
      authorizationParams: {
        audience: AUTH0_AUDIENCE,
        ...(_resolvedAuth0Org ? { organization: _resolvedAuth0Org } : {}),
      },
    });
  }, [loginWithRedirect]);

  const loginWithCredentials = useCallback(
    async (_email: string, _password: string) => {
      await loginWithRedirect({
        authorizationParams: {
          audience: AUTH0_AUDIENCE,
          ...(_resolvedAuth0Org ? { organization: _resolvedAuth0Org } : {}),
        },
      });
    },
    [loginWithRedirect]
  );

  const logout = useCallback(() => {
    auth0Logout({
      logoutParams: {
        returnTo: window.location.origin,
      },
    });
  }, [auth0Logout]);

  const getAccessToken = useCallback(async () => {
    try {
      const token = await getAccessTokenSilently({
        authorizationParams: {
          audience: AUTH0_AUDIENCE,
        },
      });
      return token;
    } catch (err) {
      console.error("[Heimdex] Failed to get access token:", err);
      return null;
    }
  }, [getAccessTokenSilently]);

  const value: AuthContextType = {
    isAuthenticated,
    isLoading,
    user: user
      ? {
          email: user.email,
          name: user.name,
          picture: user.picture,
          role: dbRole,
        }
      : null,
    error: error || null,
    login,
    loginWithCredentials,
    logout,
    getAccessToken,
    isAuth0Enabled: true,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// Main AuthProvider that switches between Auth0 and dev mode
export function AuthProvider({ children }: { children: ReactNode }) {
  // SSR guard: Auth0Provider requires a browser context. During SSR, render
  // the dev provider (which returns a safe loading state) to avoid the SDK
  // throwing null when window/document are unavailable.
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    fetchAuth0OrgId().then(() => setMounted(true));
  }, []);

  if (!AUTH0_ENABLED || !mounted) {
    return <DevAuthProvider>{children}</DevAuthProvider>;
  }

  const redirectUri = `${window.location.origin}/auth/callback`;

  const authParams = {
    redirect_uri: redirectUri,
    audience: AUTH0_AUDIENCE,
    scope: "openid profile email",
    ...(_resolvedAuth0Org ? { organization: _resolvedAuth0Org } : {}),
  };

  return (
    <Auth0Provider
      domain={AUTH0_DOMAIN}
      clientId={AUTH0_CLIENT_ID}
      authorizationParams={authParams}
      cacheLocation="memory" // More secure than localStorage
      useRefreshTokens={true}
      useRefreshTokensFallback={true}
    >
      <Auth0AuthProvider>{children}</Auth0AuthProvider>
    </Auth0Provider>
  );
}

// Export for checking auth mode
export const isAuth0Enabled = AUTH0_ENABLED;
