"use client";

import { Trash2 } from "lucide-react";

// figma: 1713:274808 — 자막 박스/취소 액션바 (w=206 h=46 r=10, padLR=16 padTB=8, gap=20)
interface SubtitleCancelActionBarProps {
  text: string;
  onRemove: () => void;
}

export function SubtitleCancelActionBar({
  text,
  onRemove,
}: SubtitleCancelActionBarProps) {
  return (
    <button
      type="button"
      onClick={onRemove}
      className="inline-flex h-[46px] w-[206px] items-center gap-5 rounded-card bg-white px-4 py-2 text-left shadow-input hover:bg-grayscale-10"
    >
      {/* figma: I1713:274808;1669:49430 — inner frame gap=10 */}
      <span className="flex min-w-0 flex-1 items-center gap-2.5">
        {/* figma: I1713:274808;1669:49431 — "선택" fs=14 fw=500 */}
        <span className="shrink-0 text-sm font-medium text-grayscale-500">선택</span>
        {/* figma: I1713:274808;1669:49432 — "취소할 내용" fs=14 fw=500 */}
        <span className="truncate text-sm font-medium text-grayscale-800">
          {text || "취소할 내용"}
        </span>
      </span>
      {/* figma: I1713:274808;1669:49433 — Primary trash 30×30 r≈6.67 */}
      <span className="flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-[7px] text-red-h-500">
        <Trash2 className="h-4 w-4" strokeWidth={1.5} />
      </span>
    </button>
  );
}
