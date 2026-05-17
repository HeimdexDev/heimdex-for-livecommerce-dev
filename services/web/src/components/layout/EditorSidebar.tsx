"use client";

// Editor 라우트 전용 LNB. 4개 메뉴(동영상 검색·이미지 검색·인물 라벨 관리·쇼츠)만
// 노출하는 64px 콜랩스 모드 + PanelLeft 클릭 시 270px overlay 펼침.
// AppLayout main 은 ml-16 고정 — 펼침은 우측 메인 위로 덮기만 함(밀지 않음).
// 라우트 분기는 AppLayout 의 EDITOR_ROUTE_PATTERNS 에서 처리.

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { PanelLeft } from "lucide-react";
import { cn } from "@/lib/utils";

function SettingsCubeIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="20"
      height="20"
      viewBox="0 0 20 20"
      fill="none"
      aria-hidden
    >
      <path
        d="M17.5 13.3329V6.66626C17.4997 6.37399 17.4225 6.08693 17.2763 5.8339C17.13 5.58086 16.9198 5.37073 16.6667 5.22459L10.8333 1.89126C10.58 1.74498 10.2926 1.66797 10 1.66797C9.70744 1.66797 9.42003 1.74498 9.16667 1.89126L3.33333 5.22459C3.08022 5.37073 2.86998 5.58086 2.72372 5.8339C2.57745 6.08693 2.5003 6.37399 2.5 6.66626V13.3329C2.5003 13.6252 2.57745 13.9123 2.72372 14.1653C2.86998 14.4183 3.08022 14.6285 3.33333 14.7746L9.16667 18.1079C9.42003 18.2542 9.70744 18.3312 10 18.3312C10.2926 18.3312 10.58 18.2542 10.8333 18.1079L16.6667 14.7746C16.9198 14.6285 17.13 14.4183 17.2763 14.1653C17.4225 13.9123 17.4997 13.6252 17.5 13.3329Z"
        stroke="currentColor"
        strokeWidth="1.66667"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M10 13.3329C11.8409 13.3329 13.3333 11.8405 13.3333 9.99959C13.3333 8.15864 11.8409 6.66626 10 6.66626C8.15905 6.66626 6.66667 8.15864 6.66667 9.99959C6.66667 11.8405 8.15905 13.3329 10 13.3329Z"
        stroke="currentColor"
        strokeWidth="1.66667"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

interface EditorSidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

type EditorNavItem = {
  label: string;
  href: string;
  icon: React.ReactNode;
};

const editorNavItems: EditorNavItem[] = [
  {
    label: "동영상 검색",
    href: "/",
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
        <path
          d="M13.3337 10.8333L17.6862 13.735C17.7489 13.7768 17.8218 13.8007 17.8971 13.8043C17.9724 13.8079 18.0472 13.791 18.1137 13.7555C18.1801 13.7199 18.2357 13.6669 18.2744 13.6023C18.3131 13.5376 18.3336 13.4637 18.3337 13.3883V6.55833C18.3337 6.48502 18.3144 6.413 18.2776 6.34954C18.2409 6.28608 18.1881 6.23344 18.1245 6.19692C18.061 6.1604 17.9889 6.1413 17.9156 6.14155C17.8423 6.14179 17.7703 6.16138 17.707 6.19833L13.3337 8.75M3.33366 5H11.667C12.5875 5 13.3337 5.74619 13.3337 6.66667V13.3333C13.3337 14.2538 12.5875 15 11.667 15H3.33366C2.41318 15 1.66699 14.2538 1.66699 13.3333V6.66667C1.66699 5.74619 2.41318 5 3.33366 5Z"
          stroke="currentColor"
          strokeWidth="1.66667"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    ),
  },
  {
    label: "이미지 검색",
    href: "/images",
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
        <path
          d="M17.5 12.5L14.9283 9.92833C14.6158 9.61588 14.1919 9.44036 13.75 9.44036C13.3081 9.44036 12.8842 9.61588 12.5717 9.92833L5 17.5M4.16667 2.5H15.8333C16.7538 2.5 17.5 3.24619 17.5 4.16667V15.8333C17.5 16.7538 16.7538 17.5 15.8333 17.5H4.16667C3.24619 17.5 2.5 16.7538 2.5 15.8333V4.16667C2.5 3.24619 3.24619 2.5 4.16667 2.5ZM9.16667 7.5C9.16667 8.42047 8.42047 9.16667 7.5 9.16667C6.57953 9.16667 5.83333 8.42047 5.83333 7.5C5.83333 6.57953 6.57953 5.83333 7.5 5.83333C8.42047 5.83333 9.16667 6.57953 9.16667 7.5Z"
          stroke="currentColor"
          strokeWidth="1.66667"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    ),
  },
  {
    label: "인물 라벨 관리",
    href: "/settings/people",
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
        <path
          d="M9.99967 10.8333C12.3009 10.8333 14.1663 8.96785 14.1663 6.66667C14.1663 4.36548 12.3009 2.5 9.99967 2.5C7.69849 2.5 5.83301 4.36548 5.83301 6.66667C5.83301 8.96785 7.69849 10.8333 9.99967 10.8333ZM9.99967 10.8333C11.7678 10.8333 13.4635 11.5357 14.7137 12.786C15.964 14.0362 16.6663 15.7319 16.6663 17.5M9.99967 10.8333C8.23156 10.8333 6.53587 11.5357 5.28563 12.786C4.03539 14.0362 3.33301 15.7319 3.33301 17.5"
          stroke="currentColor"
          strokeWidth="1.66667"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    ),
  },
  {
    label: "쇼츠",
    href: "/export/shorts",
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
        <path
          d="M14.1667 17.5V11.6667C14.1667 11.4457 14.0789 11.2337 13.9226 11.0774C13.7663 10.9211 13.5543 10.8333 13.3333 10.8333H6.66667C6.44565 10.8333 6.23369 10.9211 6.07741 11.0774C5.92113 11.2337 5.83333 11.4457 5.83333 11.6667V17.5M5.83333 2.5V5.83333C5.83333 6.05435 5.92113 6.26631 6.07741 6.42259C6.23369 6.57887 6.44565 6.66667 6.66667 6.66667H12.5M12.6667 2.5C13.1063 2.50626 13.5256 2.68598 13.8333 3L17 6.16667C17.314 6.47438 17.4937 6.89372 17.5 7.33333V15.8333C17.5 16.2754 17.3244 16.6993 17.0118 17.0118C16.6993 17.3244 16.2754 17.5 15.8333 17.5H4.16667C3.72464 17.5 3.30072 17.3244 2.98816 17.0118C2.67559 16.6993 2.5 16.2754 2.5 15.8333V4.16667C2.5 3.72464 2.67559 3.30072 2.98816 2.98816C3.30072 2.67559 3.72464 2.5 4.16667 2.5H12.6667Z"
          stroke="currentColor"
          strokeWidth="1.66667"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    ),
  },
];

function isLinkActive(href: string, pathname: string): boolean {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

// editor LNB overlay 모드
// onToggle prop 은 외부 collapsed(w-0) 토글용으로 interface 유지하되 내부에서는 미사용.
// PanelLeft 는 내부 expanded state(64↔270) 만 토글. AppLayout main ml-16 고정으로 메인을 밀지 않고 위로 덮음.
export function EditorSidebar({ collapsed }: EditorSidebarProps) {
  const pathname = usePathname();
  const [expanded, setExpanded] = useState(false);

  return (
    <aside
      className={cn(
        // overlay 강조: z-50 + transition-[width] duration-200
        "fixed left-0 top-0 z-50 h-screen border-r border-gray-200 bg-white transition-[width] duration-200 ease-in-out",
        collapsed ? "w-0 overflow-hidden" : expanded ? "w-[270px]" : "w-16",
      )}
    >
      <div
        className={cn(
          "flex flex-col h-full transition-[width] duration-200 ease-in-out",
          expanded ? "w-[270px]" : "w-16",
        )}
      >
        {/* 2026-05-17: 64px LNB 에서 heimdex 로고 영역 제거 (깨짐 이슈 — 사용자 spec). */}
        {/* PanelLeft 클릭 → 64↔270 토글 (overlay) */}
        <div
          className={cn(
            "flex items-center pt-6 pb-2",
            expanded ? "justify-end pr-3" : "justify-center",
          )}
        >
          <button
            type="button"
            onClick={() => setExpanded((prev) => !prev)}
            className="rounded-md p-1 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
            aria-label={expanded ? "사이드바 접기" : "사이드바 펼치기"}
          >
            <PanelLeft className="h-5 w-5" strokeWidth={2} />
          </button>
        </div>

        <nav className="flex flex-col gap-1 px-2 pt-2">
          {editorNavItems.map((item) => {
            const active = isLinkActive(item.href, pathname);
            return (
              <Link
                key={item.href}
                href={item.href}
                title={item.label}
                aria-label={item.label}
                className={cn(
                  // 펼침 시 라벨 동반
                  "flex h-10 items-center rounded-md transition-colors",
                  expanded ? "w-full gap-3 px-3" : "w-12 justify-center",
                  active
                    ? "bg-grayscale-200 text-grayscale-800"
                    : "text-grayscale-800 hover:bg-grayscale-100",
                )}
              >
                <span className="flex-shrink-0">{item.icon}</span>
                {expanded && (
                  <span className="text-base font-medium text-grayscale-800">
                    {item.label}
                  </span>
                )}
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto border-t border-gray-200 px-2 py-3">
          <Link
            href="/settings"
            title="설정"
            aria-label="설정"
            className={cn(
              "flex h-10 items-center rounded-md transition-colors",
              expanded ? "w-full gap-3 px-3" : "w-12 justify-center",
              pathname === "/settings"
                ? "bg-grayscale-200 text-grayscale-800"
                : "text-grayscale-800 hover:bg-grayscale-100",
            )}
          >
            <SettingsCubeIcon className="h-5 w-5 flex-shrink-0" />
            {expanded && (
              <span className="text-base font-medium text-grayscale-800">설정</span>
            )}
          </Link>
        </div>
      </div>
    </aside>
  );
}
