"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { LoginForm } from "@/components/login/LoginForm";
import { Auth0LoginPrompt } from "@/components/login/Auth0LoginPrompt";
import { LoginLogoWhite } from "@/components/login/LoginLogoWhite";

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
    <div className="min-h-screen flex items-center bg-grayscale-10">
      {/* Left navy panel — visible on lg and above */}
      <div
        className="hidden lg:flex flex-col items-center justify-center bg-heimdex-navy-500 shadow-left-pane shrink-0"
        style={{
          display: "flex",
          width: "856px",
          height: "1024px",
          minWidth: "564px",
          maxWidth: "856px",
          padding: "372px 259px",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "center",
          gap: "10px",
          flexShrink: 0,
          borderTopRightRadius: "40px",
          borderBottomRightRadius: "40px",
        }}
      >
        <LoginLogoWhite />
      </div>

      {/* Right form panel */}
      <div className="flex-1 flex h-full items-center justify-center overflow-clip px-8 py-12 lg:px-[97px] lg:py-[220px]">
        {isAuth0Enabled ? <Auth0LoginPrompt /> : <LoginForm />}
      </div>
    </div>
  );
}
