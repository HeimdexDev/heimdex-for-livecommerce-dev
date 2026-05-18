"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { PanelLeft } from "lucide-react";
import { HeimdexBrand } from "@/components/icons/figma";
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

type NavLinkItem = { kind: "link"; label: string; href: string; badge?: string };
type NavGroupItem = {
  kind: "group";
  label: string;
  children: { label: string; href: string; badge?: string }[];
};
type NavItem = NavLinkItem | NavGroupItem;

const navItems: NavItem[] = [
  { kind: "link", label: "동영상 검색", href: "/" },
  { kind: "link", label: "이미지 검색", href: "/images", badge: "Pro" },
  { kind: "link", label: "파일 동기화", href: "/sync" },
  { kind: "link", label: "인물 라벨 관리", href: "/settings/people" },
  {
    kind: "group",
    label: "내보내기",
    children: [
      { label: "쇼츠", href: "/export/shorts" },
      { label: "가편집", href: "/export/preedit" },
      { label: "문서", href: "/export/documents" },
    ],
  },
  { kind: "link", label: "에이전트", href: "/agent" },
];

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

const EXPORT_GROUP_STORAGE_KEY = "heimdex-export-group-expanded";

function readExportGroupState(): boolean {
  if (typeof window === "undefined") return true;
  try {
    const val = localStorage.getItem(EXPORT_GROUP_STORAGE_KEY);
    return val === null ? true : val === "true";
  } catch {
    return true;
  }
}

function writeExportGroupState(expanded: boolean): void {
  try {
    localStorage.setItem(EXPORT_GROUP_STORAGE_KEY, String(expanded));
  } catch {
    /* localStorage unavailable */
  }
}

function GroupChevron({ expanded }: { expanded: boolean }) {
  return (
    <svg
      className={cn(
        "h-3.5 w-3.5 transition-transform duration-300",
        !expanded && "-rotate-90",
      )}
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
    </svg>
  );
}

function isLinkActive(href: string, pathname: string): boolean {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

function NavLink({
  label,
  href,
  badge,
  pathname,
  indent,
}: {
  label: string;
  href: string;
  badge?: string;
  pathname: string;
  indent?: boolean;
}) {
  const isActive = isLinkActive(href, pathname);

  return (
    <Link
      href={href}
      className={cn(
        "relative flex items-center gap-2.5 rounded-r-md px-3 py-2 text-sm transition-colors",
        isActive
          ? "border-l-[3px] border-indigo-500 font-medium text-gray-900"
          : "border-l-[3px] border-transparent text-gray-600 hover:bg-gray-50",
        indent && "pl-7",
      )}
    >
      <span
        className={cn(
          "h-1.5 w-1.5 flex-shrink-0 rounded-full",
          isActive ? "bg-indigo-500" : "bg-indigo-400",
        )}
      />
      {label}
      {badge && (
        <span className="ml-auto rounded-full bg-indigo-100 px-1.5 py-0.5 text-[10px] font-semibold leading-none text-indigo-600">
          {badge}
        </span>
      )}
    </Link>
  );
}

function NavGroup({
  item,
  pathname,
}: {
  item: NavGroupItem;
  pathname: string;
}) {
  const isChildActive = item.children.some((child) =>
    pathname.startsWith(child.href),
  );

  const [expanded, setExpanded] = useState(() => {
    const stored = readExportGroupState();
    return isChildActive ? true : stored;
  });

  function handleToggle() {
    const next = !expanded;
    setExpanded(next);
    writeExportGroupState(next);
  }

  return (
    <div>
      <button
        type="button"
        onClick={handleToggle}
        className={cn(
          "relative flex w-full items-center gap-2.5 rounded-r-md px-3 py-2 text-sm transition-colors",
          isChildActive
            ? "border-l-[3px] border-indigo-500 font-medium text-gray-900"
            : "border-l-[3px] border-transparent text-gray-600 hover:bg-gray-50",
        )}
      >
        <span
          className={cn(
            "h-1.5 w-1.5 flex-shrink-0 rounded-full",
            isChildActive ? "bg-indigo-500" : "bg-indigo-400",
          )}
        />
        {item.label}
        <span className="ml-auto">
          <GroupChevron expanded={expanded} />
        </span>
      </button>

      {expanded && (
        <div className="flex flex-col gap-0.5">
          {item.children.map((child) => (
            <NavLink
              key={child.href}
              label={child.label}
              href={child.href}
              badge={child.badge}
              pathname={pathname}
              indent
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const pathname = usePathname();

  return (
    <aside
      className={cn(
        "fixed left-0 top-0 z-40 h-screen border-r border-gray-200 bg-white transition-[width] duration-300 ease-in-out",
        collapsed ? "w-0 overflow-hidden" : "w-[270px]",
      )}
    >
      <div className="flex w-[270px] flex-col h-full">
        <div className="flex items-center justify-between pr-2">
          <Link href="/" className="flex items-center px-5 py-6">
            <HeimdexBrand />
          </Link>

          <button
            type="button"
            onClick={onToggle}
            className="rounded-md p-1 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
            aria-label="사이드바 접기"
          >
            <PanelLeft className="h-5 w-5" strokeWidth={2} />
          </button>
        </div>

        <div className="px-5 pb-2 pt-4">
          <span className="text-xs font-medium text-gray-400">메인</span>
        </div>

        <nav className="flex flex-col gap-0.5 px-2">
          {navItems.map((item) =>
            item.kind === "group" ? (
              <NavGroup key={item.label} item={item} pathname={pathname} />
            ) : (
              <NavLink
                key={item.href}
                label={item.label}
                href={item.href}
                badge={item.badge}
                pathname={pathname}
              />
            ),
          )}
        </nav>

        <div className="mt-auto border-t border-gray-200 px-2 py-3">
          <Link
            href="/settings"
            aria-label="설정"
            className={cn(
              "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
              pathname === "/settings"
                ? "bg-gray-100 font-medium text-gray-900"
                : "text-gray-600 hover:bg-gray-50",
            )}
          >
            <SettingsCubeIcon className="h-5 w-5" />
            <span>설정</span>
          </Link>
        </div>
      </div>
    </aside>
  );
}
