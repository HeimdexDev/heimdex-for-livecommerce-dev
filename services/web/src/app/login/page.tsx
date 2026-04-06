"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { LoginForm } from "@/components/login/LoginForm";
import { Auth0LoginPrompt } from "@/components/login/Auth0LoginPrompt";
import { HeimdexLogo } from "@/components/login/HeimdexLogo";

export default function LoginPage() {
  const router = useRouter();
  const { isAuthenticated, isLoading, isAuth0Enabled } = useAuth();

  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      const returnTo = sessionStorage.getItem("heimdex_return_to") || "/";
      sessionStorage.removeItem("heimdex_return_to");
      router.replace(returnTo);
    }
  }, [isAuthenticated, isLoading, router]);

  if (isLoading || isAuthenticated) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-500" />
      </div>
    );
  }

  return (
    <div className="flex min-h-screen">
      <div className="hidden lg:flex lg:w-[55%] relative overflow-hidden items-center justify-center bg-[#EEEAF4]">
        <div className="absolute top-0 left-0 w-[70%] h-48 bg-gradient-to-br from-indigo-300/50 via-purple-200/30 to-transparent rounded-br-[100px]" />
        <div className="relative z-10">
          <HeimdexLogo />
        </div>
      </div>

      <div className="flex-1 flex flex-col items-center justify-center px-8 lg:px-16 bg-white">
        <div className="w-full max-w-[380px]">
          <div className="lg:hidden mb-12 flex justify-center">
            <HeimdexLogo />
          </div>

          {isAuth0Enabled ? <Auth0LoginPrompt /> : <LoginForm />}

          <div className="mt-16 text-center text-sm text-gray-500">
            Contact us{" "}
            <a
              href="mailto:heimdex@heimdex.co"
              className="text-gray-700 underline underline-offset-2 hover:text-gray-900 transition-colors"
            >
              heimdex@heimdex.co
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}
