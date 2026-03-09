"use client";

import { cn } from "@/lib/utils";
import { Tooltip } from "@/components/ui/Tooltip";
import type { SearchMode } from "@/lib/types/search";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------
interface SearchModeToggleProps {
  value: SearchMode;
  onChange: (value: SearchMode) => void;
}

// ---------------------------------------------------------------------------
// Mode config — order determines render order
// ---------------------------------------------------------------------------
const MODES: { key: SearchMode; icon: string; label: string; description: string }[] = [
  { key: "metadata", icon: "📋", label: "파일 검색", description: "파일 이름, 날짜 등 메타데이터로 검색" },
  { key: "lexical", icon: "📝", label: "내용 검색", description: "자막, OCR, 캡션 텍스트 일치 검색" },
  { key: "semantic", icon: "🧠", label: "의미 검색", description: "AI가 의미를 이해하여 유사 장면 검색" },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export function SearchModeToggle({ value, onChange }: SearchModeToggleProps) {
  return (
    <div
      role="radiogroup"
      aria-label="검색 모드"
      className="inline-flex h-9 items-center rounded-full bg-gray-100 p-1"
    >
      {MODES.map(({ key, icon, label, description }) => {
        const isActive = value === key;
        return (
          <Tooltip key={key} content={description}>
            <button
              role="radio"
              aria-checked={isActive}
              aria-label={label}
              type="button"
              onClick={() => onChange(key)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-all",
                isActive
                  ? "bg-white text-gray-900 shadow-sm"
                  : "text-gray-500 hover:text-gray-700",
              )}
            >
              <span className="text-sm leading-none" aria-hidden>
                {icon}
              </span>
              {label}
              <span
                aria-hidden
                className={cn(
                  "ml-0.5 inline-flex h-3.5 w-3.5 items-center justify-center rounded-full text-[9px] font-bold",
                  isActive
                    ? "bg-gray-300 text-gray-600"
                    : "bg-gray-300/60 text-gray-400",
                )}
              >
                ?
              </span>
            </button>
          </Tooltip>
        );
      })}
    </div>
  );
}
