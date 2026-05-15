"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { cn } from "@/lib/utils";

interface PopoverItem {
  label: string;
  onClick: () => void;
  variant?: "default" | "danger";
  highlighted?: boolean;
}

interface Props {
  open: boolean;
  onClose: () => void;
  items: PopoverItem[];
  anchor?: ReactNode;
  className?: string;
}

export function Popover({ open, onClose, items, anchor, className }: Props) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open, onClose]);

  return (
    <div ref={ref} className="relative inline-block">
      {anchor}
      {open ? (
        <div
          role="menu"
          className={cn(
            "absolute right-0 top-full z-20 mt-2 flex min-w-[100px] flex-col rounded-card bg-white shadow-dialog overflow-hidden",
            className,
          )}
        >
          {items.map((item, i) => (
            <button
              key={`${item.label}-${i}`}
              type="button"
              onClick={() => {
                item.onClick();
                onClose();
              }}
              className={cn(
                "px-[10px] py-[8px] text-left font-pretendard text-[10px] font-medium tracking-[-0.25px] leading-[1.4] hover:bg-neutral-h-50",
                item.variant === "danger"
                  ? "text-red-h-500"
                  : "text-grayscale-800",
                item.highlighted && "bg-neutral-h-50",
              )}
              role="menuitem"
            >
              {item.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
