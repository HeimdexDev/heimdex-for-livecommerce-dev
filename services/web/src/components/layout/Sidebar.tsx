"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LogoIcon, LogoText } from "@/components/login/HeimdexLogo";
import { cn } from "@/lib/utils";

const navItems: { label: string; href: string; badge?: string }[] = [
  { label: "전체 아카이브 검색", href: "/" },
  { label: "이미지 검색", href: "/images", badge: "Pro" },
  { label: "파일 동기화", href: "/sync" },
  { label: "인물 라벨 관리", href: "/settings/people" },
  { label: "저장된 쇼츠", href: "/shorts" },
  { label: "에이전트", href: "/agent" },
];

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

function CollapseChevron({ collapsed }: { collapsed: boolean }) {
  return (
    <svg
      className={cn(
        "h-4 w-4 transition-transform duration-300",
        collapsed && "rotate-180",
      )}
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
    </svg>
  );
}

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const pathname = usePathname();

  return (
    <aside
      className={cn(
        "fixed left-0 top-0 z-40 h-screen border-r border-gray-200 bg-white transition-[width] duration-300 ease-in-out",
        collapsed ? "w-0 overflow-hidden" : "w-[200px]",
      )}
    >
      <div className="flex w-[200px] flex-col h-full">
        <div className="flex items-center justify-between pr-2">
          <Link href="/" className="flex items-center gap-2 px-5 py-6">
            <LogoIcon className="h-7 w-7 flex-shrink-0" />
            <LogoText className="w-[100px]" />
          </Link>

          <button
            type="button"
            onClick={onToggle}
            className="rounded-md p-1 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
            aria-label="사이드바 접기"
          >
            <CollapseChevron collapsed={collapsed} />
          </button>
        </div>

        <div className="px-5 pb-2 pt-4">
          <span className="text-xs font-medium text-gray-400">메인</span>
        </div>

        <nav className="flex flex-col gap-0.5 px-2">
          {navItems.map((item) => {
            const isActive =
              item.href === "/"
                ? pathname === "/"
                : pathname.startsWith(item.href);

            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "relative flex items-center gap-2.5 rounded-r-md px-3 py-2 text-sm transition-colors",
                  isActive
                    ? "border-l-[3px] border-indigo-500 bg-gray-100 font-medium text-gray-900"
                    : "border-l-[3px] border-transparent text-gray-600 hover:bg-gray-50"
                )}
              >
                <span
                  className={cn(
                    "h-1.5 w-1.5 flex-shrink-0 rounded-full",
                    isActive ? "bg-indigo-500" : "bg-indigo-400"
                  )}
                />
                {item.label}
                {item.badge && (
                  <span className="ml-auto rounded-full bg-indigo-100 px-1.5 py-0.5 text-[10px] font-semibold leading-none text-indigo-600">
                    {item.badge}
                  </span>
                )}
              </Link>
            );
          })}
        </nav>
      </div>
    </aside>
  );
}
