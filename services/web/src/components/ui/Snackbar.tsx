// figma: 1713:288017  (cache: .figma-cache/1713-287987_phase4_saved-shorts.api.json)
// node-name: Loading · spec: 24×24, double ellipse stroke=3, track=#E8E9F8 grayscale-100, arc=#234C77 heimdex-navy-500 ~288° round cap

import type { ReactNode } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { WarningIcon } from "@/components/icons/figma";

type Tone = "warning" | "loading" | "info";
type Position = "bottom-center" | "top-right";

interface Props {
  tone?: Tone;
  title: ReactNode;
  body?: ReactNode;
  position?: Position;
  onClose?: () => void;
  className?: string;
}

const positionClasses: Record<Position, string> = {
  "bottom-center":
    "fixed bottom-[40px] left-1/2 -translate-x-1/2 w-[364px]",
  "top-right": "fixed top-[80px] right-[20px] w-[364px]",
};

function LeadingIcon({ tone }: { tone: Tone }) {
  if (tone === "warning") {
    return <WarningIcon className="h-[24px] w-[24px] shrink-0" />;
  }
  if (tone === "loading") {
    return (
      <svg
        viewBox="0 0 24 24"
        fill="none"
        aria-hidden="true"
        className="h-6 w-6 shrink-0 animate-spin"
      >
        <circle
          cx="12"
          cy="12"
          r="10.5"
          strokeWidth="3"
          className="stroke-grayscale-100"
        />
        <circle
          cx="12"
          cy="12"
          r="10.5"
          strokeWidth="3"
          strokeLinecap="round"
          strokeDasharray="52.8 13.2"
          transform="rotate(-90 12 12)"
          className="stroke-heimdex-navy-500"
        />
      </svg>
    );
  }
  return null;
}

export function Snackbar({
  tone = "warning",
  title,
  body,
  position = "bottom-center",
  onClose,
  className,
}: Props) {
  return (
    <div
      role="status"
      className={cn(
        "z-50 flex items-start gap-[8px] rounded-card bg-white p-[16px] shadow-dialog",
        positionClasses[position],
        className,
      )}
    >
      <LeadingIcon tone={tone} />
      <div className="flex min-w-0 flex-1 flex-col gap-[8px] leading-[1.4]">
        <p className="font-pretendard text-[18px] font-bold tracking-[-0.45px] text-neutral-h-800">
          {title}
        </p>
        {body ? (
          <p className="font-pretendard text-[16px] font-medium tracking-[-0.4px] text-neutral-h-600">
            {body}
          </p>
        ) : null}
      </div>
      {onClose ? (
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 text-neutral-h-500 hover:text-neutral-h-800"
          aria-label="닫기"
        >
          <X className="h-[24px] w-[24px]" strokeWidth={2} />
        </button>
      ) : null}
    </div>
  );
}
