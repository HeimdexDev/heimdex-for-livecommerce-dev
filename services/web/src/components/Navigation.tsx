"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth, getOrgSlug } from "@/lib/auth";
import { useAgent } from "@/features/search/hooks/useAgent";
import { cn } from "@/lib/utils";

export function Navigation() {
  const pathname = usePathname();
  const { isAuthenticated, isLoading: authLoading, user, login, logout, isAuth0Enabled } = useAuth();
  const { isAvailable: agentAvailable } = useAgent();
  const [orgSlug, setOrgSlug] = useState("");

  useEffect(() => {
    setOrgSlug(getOrgSlug());
  }, []);

  const tabs = [
    { label: "Search", href: "/" },
    { label: "Videos", href: "/videos" },
    { label: "Settings", href: "/settings/devices" },
  ];

  return (
    <header className="relative z-[60] bg-white border-b border-gray-200">
      <div className="max-w-7xl mx-auto px-4 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-primary-600 rounded-lg flex items-center justify-center">
                <svg
                  className="w-6 h-6 text-white"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
                  />
                </svg>
              </div>
              <div>
                <h1 className="text-xl font-bold text-gray-900">Heimdex</h1>
                <p className="text-xs text-gray-500">Video Search Platform</p>
              </div>
            </div>

            <nav className="flex items-center gap-1">
              {tabs.map((tab) => {
                const isActive =
                  tab.href === "/"
                    ? pathname === "/"
                    : pathname.startsWith(tab.href);
                return (
                  <Link
                    key={tab.href}
                    href={tab.href}
                    className={cn(
                      "px-4 py-2 text-sm font-medium rounded-lg transition-colors",
                      isActive
                        ? "bg-primary-600 text-white"
                        : "text-gray-600 hover:text-gray-900 hover:bg-gray-100",
                    )}
                  >
                    {tab.label}
                  </Link>
                );
              })}
            </nav>
          </div>

          <div className="flex items-center gap-4">
            <span className="text-sm text-gray-500">
              Org: <span className="font-medium text-gray-700">{orgSlug || "..."}</span>
            </span>

            <span className="flex items-center gap-1.5 text-xs text-gray-500">
              <span
                className={cn(
                  "w-2 h-2 rounded-full",
                  agentAvailable ? "bg-green-500" : "bg-gray-300",
                )}
              />
              {agentAvailable ? "Agent connected" : "Agent offline"}
            </span>

            {authLoading ? (
              <span className="text-sm text-gray-400">Loading...</span>
            ) : isAuthenticated ? (
              <div className="flex items-center gap-3">
                <span className="text-sm text-gray-600">
                  {user?.email || "User"}
                </span>
                <button
                  onClick={logout}
                  className="px-3 py-1.5 text-sm font-medium text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-lg transition-colors"
                >
                  Logout
                </button>
              </div>
            ) : (
              <button
                onClick={login}
                className="px-4 py-1.5 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 rounded-lg transition-colors"
              >
                {isAuth0Enabled ? "Login" : "Dev Login"}
              </button>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
