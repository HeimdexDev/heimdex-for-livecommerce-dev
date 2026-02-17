"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LogoIcon, LogoText } from "@/components/login/HeimdexLogo";
import { cn } from "@/lib/utils";

const navItems = [
  { label: "전체 아카이브 검색", href: "/" },
  { label: "파일 동기화", href: "/sync" },
  { label: "인물 라벨 관리", href: "/settings/people" },
  { label: "저장된 숏츠", href: "/videos" },
  { label: "에이전트", href: "/agent" },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed left-0 top-0 z-40 h-screen w-[200px] border-r border-gray-200 bg-white">
      <Link href="/" className="flex items-center gap-2 px-5 py-6">
        <LogoIcon className="h-7 w-7 flex-shrink-0" />
        <LogoText className="w-[100px]" />
      </Link>

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
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
