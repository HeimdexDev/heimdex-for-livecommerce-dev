"use client";

// figma: 1602:36895  (cache: .figma-cache/1602-36895_phase3_cancel-dialog.api.json)
// node-name: 삭제 팝업 · spec: w=286, padding=24, gap=28, cornerRadius=20

import { useEffect, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { WarningIcon } from "@/components/icons/figma";
import { Button } from "./Button";

type IconKind = "warning" | "none";

interface DialogAction {
  label: string;
  onClick: () => void;
}

interface Props {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  body?: ReactNode;
  icon?: IconKind;
  primary: DialogAction & { variant?: "primary" | "danger" };
  secondary?: DialogAction;
  className?: string;
}

export function Dialog({
  open,
  onClose,
  title,
  body,
  icon = "warning",
  primary,
  secondary,
  className,
}: Props) {
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className={cn(
          "flex w-dialog flex-col items-center gap-[28px] rounded-dialog bg-white p-[24px] shadow-dialog",
          className,
        )}
      >
        <div className="flex w-full flex-col items-center justify-center gap-[12px]">
          {icon === "warning" ? (
            <WarningIcon className="h-[24px] w-[24px]" />
          ) : null}
          <p className="font-pretendard text-[18px] font-bold tracking-[-0.45px] leading-[1.4] text-neutral-h-800">
            {title}
          </p>
          {body ? (
            <p className="w-full text-center font-pretendard text-[14px] font-medium tracking-[-0.35px] leading-[1.4] text-grayscale-800">
              {body}
            </p>
          ) : null}
        </div>
        <div className="flex w-[128px] items-start gap-[8px]">
          {secondary ? (
            <Button
              variant="secondary"
              size="md"
              onClick={secondary.onClick}
              className="flex-1"
            >
              {secondary.label}
            </Button>
          ) : null}
          <Button
            variant={primary.variant ?? "primary"}
            size="md"
            onClick={primary.onClick}
            className={secondary ? "w-[60px] shrink-0" : "flex-1"}
          >
            {primary.label}
          </Button>
        </div>
      </div>
    </div>
  );
}
