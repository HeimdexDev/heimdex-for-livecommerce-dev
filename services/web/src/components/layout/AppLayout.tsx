"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { Sidebar } from "./Sidebar";
import { TopHeader } from "./TopHeader";
import { cn } from "@/lib/utils";

interface AppLayoutProps {
  children: React.ReactNode;
}

const NO_LAYOUT_ROUTES = ["/login", "/auth/"];
const SIDEBAR_STORAGE_KEY = "heimdex-sidebar-collapsed";

function readSidebarState(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return localStorage.getItem(SIDEBAR_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

function writeSidebarState(collapsed: boolean): void {
  try {
    localStorage.setItem(SIDEBAR_STORAGE_KEY, String(collapsed));
  } catch {
    /* localStorage unavailable */
  }
}

export function AppLayout({ children }: AppLayoutProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { isAuthenticated, isLoading } = useAuth();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(readSidebarState);

  const skipLayout = NO_LAYOUT_ROUTES.some((route) =>
    route.endsWith("/") ? pathname.startsWith(route) : pathname === route
  );

  useEffect(() => {
    if (!skipLayout && !isLoading && !isAuthenticated) {
      const currentPath = window.location.pathname + window.location.search;
      if (currentPath !== "/" && currentPath !== "/login") {
        sessionStorage.setItem("heimdex_return_to", currentPath);
      }
      router.replace("/login");
    }
  }, [skipLayout, isLoading, isAuthenticated, router]);

  useEffect(() => {
    writeSidebarState(sidebarCollapsed);
  }, [sidebarCollapsed]);

  const toggleSidebar = useCallback(() => {
    setSidebarCollapsed((prev) => !prev);
  }, []);

  if (skipLayout) {
    return <>{children}</>;
  }

  if (isLoading || !isAuthenticated) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="h-10 w-10 animate-spin rounded-full border-b-2 border-indigo-500" />
      </div>
    );
  }

  return (
    <div className="flex min-h-screen">
      <Sidebar collapsed={sidebarCollapsed} onToggle={toggleSidebar} />
      <div
        className={cn(
          "flex flex-1 flex-col transition-[margin-left] duration-300 ease-in-out",
          sidebarCollapsed ? "ml-0" : "ml-[200px]",
        )}
      >
        <TopHeader
          sidebarCollapsed={sidebarCollapsed}
          onToggleSidebar={toggleSidebar}
        />
        <main className="min-w-0 flex-1 overflow-hidden px-6 pb-6">{children}</main>
      </div>
    </div>
  );
}
