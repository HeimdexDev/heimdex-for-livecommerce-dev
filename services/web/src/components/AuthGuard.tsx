"use client";

import { ReactNode } from "react";
import { useAuth, getOrgSlug, isAuth0Enabled } from "@/lib/auth";

interface AuthGuardProps {
  children: ReactNode;
  /** If true, shows login prompt instead of content when not authenticated */
  requireAuth?: boolean;
}

/**
 * Guard component that handles authentication states.
 * 
 * When AUTH0 is enabled and user is not authenticated:
 * - Shows a login prompt with the organization context
 * 
 * When AUTH0 is disabled:
 * - Passes through to children (dev mode)
 * 
 * @param requireAuth - If true, shows login prompt for unauthenticated users
 */
export function AuthGuard({ children, requireAuth = true }: AuthGuardProps) {
  const { isAuthenticated, isLoading, login, error } = useAuth();

  // In dev mode (Auth0 disabled), don't require auth unless explicitly configured
  if (!isAuth0Enabled && !requireAuth) {
    return <>{children}</>;
  }

  // Show loading state
  if (isLoading) {
    return <AuthLoadingState />;
  }

  // Show error state
  if (error) {
    return <AuthErrorState error={error} onRetry={login} />;
  }

  // When Auth0 is enabled and auth is required, check authentication
  if (isAuth0Enabled && requireAuth && !isAuthenticated) {
    return <LoginPrompt onLogin={login} />;
  }

  // In dev mode with requireAuth, check if we have a token
  if (!isAuth0Enabled && requireAuth && !isAuthenticated) {
    return <DevLoginPrompt onLogin={login} />;
  }

  return <>{children}</>;
}

function AuthLoadingState() {
  return (
    <div className="min-h-[400px] flex items-center justify-center">
      <div className="text-center">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-primary-600 mx-auto mb-4"></div>
        <p className="text-gray-500">Loading...</p>
      </div>
    </div>
  );
}

function AuthErrorState({ error, onRetry }: { error: Error; onRetry: () => void }) {
  return (
    <div className="min-h-[400px] flex items-center justify-center">
      <div className="text-center max-w-md mx-auto p-6">
        <div className="text-red-500 mb-4">
          <svg className="w-12 h-12 mx-auto" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
        </div>
        <h2 className="text-lg font-semibold text-gray-900 mb-2">Authentication Error</h2>
        <p className="text-gray-600 mb-4">{error.message}</p>
        <button
          onClick={onRetry}
          className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700"
        >
          Try Again
        </button>
      </div>
    </div>
  );
}

function LoginPrompt({ onLogin }: { onLogin: () => void }) {
  const orgSlug = getOrgSlug();

  return (
    <div className="min-h-[400px] flex items-center justify-center">
      <div className="text-center max-w-md mx-auto p-8 bg-white rounded-xl shadow-lg">
        <div className="w-16 h-16 bg-primary-100 rounded-full flex items-center justify-center mx-auto mb-6">
          <svg className="w-8 h-8 text-primary-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
          </svg>
        </div>
        <h2 className="text-xl font-bold text-gray-900 mb-2">Sign In Required</h2>
        <p className="text-gray-600 mb-2">
          Access to <span className="font-semibold">{orgSlug}</span>&apos;s video library requires authentication.
        </p>
        <p className="text-sm text-gray-500 mb-6">
          Sign in with your organization account to search videos.
        </p>
        <button
          onClick={onLogin}
          className="w-full px-6 py-3 bg-primary-600 text-white font-medium rounded-lg hover:bg-primary-700 transition-colors"
        >
          Sign In
        </button>
      </div>
    </div>
  );
}

function DevLoginPrompt({ onLogin }: { onLogin: () => void }) {
  const orgSlug = getOrgSlug();

  return (
    <div className="min-h-[400px] flex items-center justify-center">
      <div className="text-center max-w-md mx-auto p-8 bg-white rounded-xl shadow-lg">
        <div className="w-16 h-16 bg-amber-100 rounded-full flex items-center justify-center mx-auto mb-6">
          <svg className="w-8 h-8 text-amber-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
          </svg>
        </div>
        <h2 className="text-xl font-bold text-gray-900 mb-2">Development Mode</h2>
        <p className="text-gray-600 mb-2">
          Sign in to <span className="font-semibold">{orgSlug}</span> using dev login.
        </p>
        <p className="text-sm text-gray-500 mb-6">
          Auth0 is disabled. Use dev-login with an existing user email.
        </p>
        <button
          onClick={onLogin}
          className="w-full px-6 py-3 bg-amber-600 text-white font-medium rounded-lg hover:bg-amber-700 transition-colors"
        >
          Dev Login
        </button>
      </div>
    </div>
  );
}
