"use client";

import { useState, useEffect, useRef, useCallback, useContext } from "react";
import Link from "next/link";
import { PanelLeft, ChevronLeft } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { getDevices } from "@/lib/api/devices";
import { ApiError } from "@/lib/types";
import type { DeviceListItem } from "@/lib/types";
import { TopHeaderActionsContext } from "./TopHeaderActionsContext";

const AGENT_STALE_MINUTES = 5;
const POLL_INTERVAL_MS = 30_000;

type AgentStatus = "connected" | "offline" | "unknown";

function deriveAgentStatus(devices: DeviceListItem[]): AgentStatus {
  const now = Date.now();
  const thresholdMs = AGENT_STALE_MINUTES * 60 * 1000;

  const hasConnected = devices.some(
    (d) =>
      !d.is_revoked &&
      d.last_seen_at !== null &&
      now - new Date(d.last_seen_at).getTime() < thresholdMs,
  );

  return hasConnected ? "connected" : "offline";
}

function AgentStatusBadge() {
  const { getAccessToken } = useAuth();
  const [status, setStatus] = useState<AgentStatus>("unknown");
  const [visible, setVisible] = useState(true);

  const poll = useCallback(async () => {
    try {
      const res = await getDevices(getAccessToken);
      setStatus(deriveAgentStatus(res.devices));
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 403) {
        setVisible(false);
        return;
      }
      setStatus("unknown");
    }
  }, [getAccessToken]);

  useEffect(() => {
    poll();
    const id = setInterval(poll, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [poll]);

  if (!visible) return null;

  const config = {
    connected: {
      dot: "bg-emerald-500",
      text: "text-emerald-700",
      bg: "bg-emerald-50 border-emerald-200",
      label: "Agent 연결됨",
    },
    offline: {
      dot: "bg-gray-400",
      text: "text-gray-500",
      bg: "bg-gray-50 border-gray-200",
      label: "Agent 오프라인",
    },
    unknown: {
      dot: "bg-gray-300",
      text: "text-gray-400",
      bg: "bg-gray-50 border-gray-200",
      label: "Agent 확인 중",
    },
  }[status];

  return (
    <div
      className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 ${config.bg}`}
    >
      <span
        className={`inline-block h-1.5 w-1.5 rounded-full ${config.dot} ${status === "connected" ? "animate-pulse" : ""}`}
      />
      <span className={`text-xs font-medium ${config.text}`}>
        {config.label}
      </span>
    </div>
  );
}

interface TopHeaderProps {
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
}

export function TopHeader({ sidebarCollapsed, onToggleSidebar }: TopHeaderProps) {
  const { user, logout } = useAuth();
  const displayName = user?.name || user?.email || "User";
  const displayEmail = user?.email || "";

  const headerActionsCtx = useContext(TopHeaderActionsContext);
  const headerActions = headerActionsCtx?.actions ?? null;
  const leftActions = headerActionsCtx?.leftActions ?? null;
  const backSlot = headerActionsCtx?.back ?? null;

  const [showDropdown, setShowDropdown] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handle(e: MouseEvent) {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node)
      ) {
        setShowDropdown(false);
      }
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, []);

  return (
    <header className="flex h-20 items-center justify-between px-8">
      <div className="flex items-center gap-5">
        {sidebarCollapsed && (
          <button
            type="button"
            onClick={onToggleSidebar}
            className="rounded-lg p-2 text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-700"
            aria-label="사이드바 열기"
          >
            <PanelLeft className="h-5 w-5" strokeWidth={2} />
          </button>
        )}
        {backSlot && (
          <button
            type="button"
            onClick={backSlot.onClick}
            className="flex shrink-0 items-center gap-1 rounded-full text-grayscale-500 hover:text-grayscale-800"
            aria-label={backSlot.label}
          >
            <ChevronLeft className="h-6 w-6" strokeWidth={2} />
            <span className="text-base font-medium tracking-[-0.4px]">
              {backSlot.label}
            </span>
          </button>
        )}
        {leftActions}
      </div>
      <div className="flex items-center gap-4">
        {headerActions}
        <AgentStatusBadge />

        <button
          type="button"
          className="rounded-lg p-2 text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-700"
          aria-label="알림"
        >
          <svg
            className="h-5 w-5"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0"
            />
          </svg>
        </button>

        <div ref={dropdownRef} className="relative">
          <button
            type="button"
            onClick={() => setShowDropdown((v) => !v)}
            className="flex items-center gap-3"
          >
            <span className="text-sm font-medium text-gray-700">
              {displayName}
            </span>
            <div className="h-9 w-9 flex-shrink-0 rounded-full bg-gray-300" />
          </button>

          {showDropdown && (
            <div className="absolute right-0 top-full z-50 mt-2 w-56 rounded-xl border border-gray-200 bg-white py-2 shadow-lg">
              <div className="border-b border-gray-100 px-4 pb-3 pt-1">
                <p className="text-sm font-medium text-gray-900">
                  {displayName}
                </p>
                {displayEmail && (
                  <p className="mt-0.5 text-xs text-gray-500">
                    {displayEmail}
                  </p>
                )}
              </div>

              <div className="py-1">
                <Link
                  href="/settings"
                  onClick={() => setShowDropdown(false)}
                  className="flex w-full items-center gap-3 px-4 py-2 text-sm text-gray-700 transition-colors hover:bg-gray-50"
                >
                  <svg
                    className="h-4 w-4 text-gray-400"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={1.5}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 010 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 010-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28z"
                    />
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                    />
                  </svg>
                  설정
                </Link>

              </div>

              <div className="border-t border-gray-100 pt-1">
                <button
                  type="button"
                  onClick={() => {
                    setShowDropdown(false);
                    logout();
                  }}
                  className="flex w-full items-center gap-3 px-4 py-2 text-sm text-red-600 transition-colors hover:bg-red-50"
                >
                  <svg
                    className="h-4 w-4 text-red-400"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={1.5}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15m3 0l3-3m0 0l-3-3m3 3H9"
                    />
                  </svg>
                  로그아웃
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
