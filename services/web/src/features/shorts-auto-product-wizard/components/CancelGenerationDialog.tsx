// figma: 1602:36895  (cache: .figma-cache/1602-36895_phase3_cancel-dialog.api.json)
"use client";

import { Dialog } from "@/components/ui/Dialog";

interface Props {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
}

export function CancelGenerationDialog({ open, onClose, onConfirm }: Props) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="취소하시겠어요?"
      body="취소한 영상은 복구할 수 없어요."
      icon="warning"
      secondary={{ label: "취소", onClick: onClose }}
      primary={{ label: "확인", variant: "danger", onClick: onConfirm }}
    />
  );
}
