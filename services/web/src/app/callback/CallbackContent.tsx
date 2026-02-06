"use client";

import { useEffect } from "react";
import { useAuth0 } from "@auth0/auth0-react";
import { useRouter } from "next/navigation";
import { isAuth0Enabled } from "@/lib/auth";

export default function CallbackContent() {
  const router = useRouter();

  if (!isAuth0Enabled) {
    return <CallbackFallback router={router} />;
  }

  return <Auth0Callback router={router} />;
}

function Auth0Callback({ router }: { router: ReturnType<typeof useRouter> }) {
  const { isLoading, error, isAuthenticated } = useAuth0();

  useEffect(() => {
    if (isLoading) return;

    if (error) {
      console.error("[Heimdex] Auth0 callback error:", error);
    }

    router.replace("/");
  }, [isLoading, error, isAuthenticated, router]);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600 mx-auto mb-4"></div>
          <p className="text-gray-600">Completing login...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center max-w-md mx-auto p-6">
          <div className="text-red-500 mb-4">
            <svg className="w-12 h-12 mx-auto" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
          <h2 className="text-lg font-semibold text-gray-900 mb-2">Login Error</h2>
          <p className="text-gray-600 mb-4">{error.message}</p>
          <button
            onClick={() => router.replace("/")}
            className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700"
          >
            Return to Home
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="text-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600 mx-auto mb-4"></div>
        <p className="text-gray-600">Redirecting...</p>
      </div>
    </div>
  );
}

function CallbackFallback({ router }: { router: ReturnType<typeof useRouter> }) {
  useEffect(() => {
    router.replace("/");
  }, [router]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="text-center">
        <p className="text-gray-600">Auth0 is not enabled. Redirecting...</p>
      </div>
    </div>
  );
}
