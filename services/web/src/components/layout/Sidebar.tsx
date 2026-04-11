"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { LogoIcon, LogoText } from "@/components/login/HeimdexLogo";
import { cn } from "@/lib/utils";

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
          ? "border-l-[3px] border-indigo-500 bg-gray-100 font-medium text-gray-900"
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
  const [userExpanded, setUserExpanded] = useState(readExportGroupState);

  const isChildActive = item.children.some((child) =>
    pathname.startsWith(child.href),
  );
  const expanded = isChildActive || userExpanded;

  function handleToggle() {
    const next = !userExpanded;
    setUserExpanded(next);
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
            ? "border-l-[3px] border-indigo-500 bg-gray-100 font-medium text-gray-900"
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
      </div>
    </aside>
  );
}
