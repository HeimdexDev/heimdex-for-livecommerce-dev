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
        "flex h-8 w-8 items-center justify-center rounded text-grayscale-500 transition-colors",
        active
          ? "bg-grayscale-200 text-grayscale-800"
          : "hover:bg-grayscale-100",
        disabled && "cursor-not-allowed opacity-40 hover:bg-transparent",
        className,
      )}
    >
      {children}
    </button>
  );
}
