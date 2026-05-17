"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface ToolbarButtonProps {
  active?: boolean;
  onClick?: () => void;
  disabled?: boolean;
  ariaLabel: string;
  tooltip?: string;
  children: ReactNode;
  className?: string;
}

/**
 * Square icon button used in formatting toolbars (B / I / U / align / fill).
 * Active state = pressed/applied; disabled state = unavailable in current
 * context (e.g. image-insert before the feature ships).
 */
export function ToolbarButton({
  active = false,
  onClick,
  disabled = false,
  ariaLabel,
  tooltip,
  children,
  className,
}: ToolbarButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={ariaLabel}
      aria-pressed={active}
      title={tooltip ?? ariaLabel}
      className={cn(
        // figma 1663:45790 — toolbar buttons are 28×28 (icon 20 + p-4) with
        // the active state lifted by a heimdex-navy/50 fill, matching the
        // 텍스트/배경 figma palette.
        "flex h-7 w-7 items-center justify-center rounded-[6px] text-grayscale-500 transition-colors",
        active
          ? "bg-heimdex-navy-50 text-heimdex-navy-500"
          : "hover:bg-grayscale-100",
        disabled && "cursor-not-allowed opacity-40 hover:bg-transparent",
        className,
      )}
    >
      {children}
    </button>
  );
}
