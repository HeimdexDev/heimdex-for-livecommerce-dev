"use client";

import { useAuth } from "@/lib/auth";

export function Auth0LoginPrompt() {
  const { login } = useAuth();

  return (
    <div>
      <p className="text-gray-500 text-[15px] mb-10">조직 계정으로 로그인해 주세요.</p>

      <button
        type="button"
        onClick={login}
        className="w-full py-3.5 rounded-lg text-sm font-medium bg-indigo-500 text-white hover:bg-indigo-600 active:bg-indigo-700 transition-colors"
      >
        Continue with Heimdex
      </button>
    </div>
  );
}
