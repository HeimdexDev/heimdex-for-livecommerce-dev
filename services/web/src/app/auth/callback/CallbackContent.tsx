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

    // Don't redirect if there's an error — let the error UI render
    if (error) {
      console.error("[Heimdex] Auth0 callback error:", error);
      return;
    }

    router.replace("/");
  }, [isLoading, error, isAuthenticated, router]);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-500 mx-auto mb-4" />
          <p className="text-gray-600">Completing login...</p>
        </div>
      </div>
    );
  }

  if (error) {
    // Check if this is an email verification error from our Post-Login Action
    const isEmailVerification =
      error.message?.includes("email_not_verified") ||
      error.message?.includes("이메일 인증");

    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center max-w-md mx-auto p-6">
          {isEmailVerification ? (
            <>
              <div className="text-indigo-400 mb-4">
                <svg className="w-16 h-16 mx-auto" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M21.75 6.75v10.5a2.25 2.25 0 0 1-2.25 2.25h-15a2.25 2.25 0 0 1-2.25-2.25V6.75m19.5 0A2.25 2.25 0 0 0 19.5 4.5h-15a2.25 2.25 0 0 0-2.25 2.25m19.5 0v.243a2.25 2.25 0 0 1-1.07 1.916l-7.5 4.615a2.25 2.25 0 0 1-2.36 0L3.32 8.91a2.25 2.25 0 0 1-1.07-1.916V6.75" />
                </svg>
              </div>
              <h2 className="text-xl font-semibold text-gray-900 mb-2">
                이메일 인증이 필요합니다
              </h2>
              <p className="text-gray-600 mb-6">
                가입 시 발송된 인증 메일을 확인해 주세요.
                이메일의 인증 링크를 클릭한 후 다시 로그인해 주세요.
              </p>
            </>
          ) : (
            <>
              <h2 className="text-lg font-semibold text-gray-900 mb-2">Login Error</h2>
              <p className="text-gray-600 mb-6">{error.message}</p>
            </>
          )}
          <button
            onClick={() => router.replace("/login")}
            className="px-6 py-2.5 bg-indigo-500 text-white rounded-lg hover:bg-indigo-600 transition-colors"
          >
            로그인 페이지로 돌아가기
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="text-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-500 mx-auto mb-4" />
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
      <p className="text-gray-600">Redirecting...</p>
    </div>
  );
}
