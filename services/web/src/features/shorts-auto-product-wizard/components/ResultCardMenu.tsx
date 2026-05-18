"use client";

import { EllipsisVertical } from "lucide-react";
import { useState } from "react";

import { Popover } from "@/components/ui/Popover";

import { CancelGenerationDialog } from "./CancelGenerationDialog";

interface Props {
  /** True when the underlying render has reached 100% — unlocks save/export items. */
  isCompleted: boolean;
  onRename: () => void;
  onSave?: () => void;
  onExport?: () => void;
  onCancel: () => void;
}

export function ResultCardMenu({
  isCompleted,
  onRename,
  onSave,
  onExport,
  onCancel,
}: Props) {
  const [open, setOpen] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);

  const items = [
    { label: "제목 변경", onClick: onRename },
    ...(isCompleted
      ? [
          { label: "저장하기", onClick: () => onSave?.() },
          { label: "내보내기", onClick: () => onExport?.() },
        ]
      : []),
    {
      label: "생성 취소",
      onClick: () => setCancelOpen(true),
      variant: "danger" as const,
    },
  ];

  return (
    <>
      <Popover
        open={open}
        onClose={() => setOpen(false)}
        items={items}
        anchor={
          <button
            type="button"
            aria-label="옵션 열기"
            data-testid="result-card-menu-trigger"
            onClick={() => setOpen((v) => !v)}
            className="inline-flex h-[24px] w-[24px] items-center justify-center rounded-[6px] text-grayscale-500 hover:bg-neutral-h-50"
          >
            <EllipsisVertical className="h-[16px] w-[16px]" />
          </button>
        }
      />
      <CancelGenerationDialog
        open={cancelOpen}
        onClose={() => setCancelOpen(false)}
        onConfirm={() => {
          setCancelOpen(false);
          onCancel();
        }}
      />
    </>
  );
}
