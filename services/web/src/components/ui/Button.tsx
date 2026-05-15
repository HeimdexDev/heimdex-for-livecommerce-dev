// figma: 1602:36903 (Secondary) / 1602:36904 (Primary)
//   cache: .figma-cache/1602-36895_phase3_cancel-dialog.api.json
// node-name: Primary/Secondary md · spec: h=36, padding L/R=12 T/B=8, gap=4, radius=8, font Pretendard 14/SemiBold(600)

import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "danger";
type Size = "sm" | "md";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  leadingIcon?: ReactNode;
  children: ReactNode;
}

const variantClasses: Record<Variant, string> = {
  primary:
    "bg-heimdex-navy-500 text-white hover:bg-heimdex-navy-600 disabled:bg-neutral-h-100 disabled:text-neutral-h-300",
  secondary:
    "border border-neutral-h-500 text-neutral-h-500 bg-white hover:bg-neutral-h-50 disabled:border-neutral-h-300 disabled:text-neutral-h-300",
  danger:
    "bg-red-h-400 text-white hover:bg-red-h-500 disabled:bg-neutral-h-100 disabled:text-neutral-h-300",
};

const sizeClasses: Record<Size, string> = {
  sm: "h-[32px] px-[10px] py-[6px] text-[12px]",
  md: "h-[36px] px-[12px] py-[8px] text-[14px]",
};

export function Button({
  variant = "primary",
  size = "sm",
  leadingIcon,
  children,
  className,
  disabled,
  ...props
}: Props) {
  return (
    <button
      type="button"
      disabled={disabled}
      className={cn(
        "inline-flex items-center justify-center gap-[4px] rounded-[8px] font-pretendard font-semibold tracking-[-0.3px] transition-colors disabled:cursor-not-allowed",
        variantClasses[variant],
        sizeClasses[size],
        className,
      )}
      {...props}
    >
      {leadingIcon ? (
        <span className="inline-flex h-[20px] w-[20px] items-center justify-center">
          {leadingIcon}
        </span>
      ) : null}
      <span className="whitespace-nowrap">{children}</span>
    </button>
  );
}
