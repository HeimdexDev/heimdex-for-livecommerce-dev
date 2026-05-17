"use client";

import { Trash2 } from "lucide-react";

// figma: 1669:49437 — element selection action bar
// spec: bg-white px-16 py-8 r-10 shadow-[2px_2px_20px_rgba(0,0,0,0.25)] gap-20
//        label "선택" 14px medium grayscale-500
//        text 14px medium grayscale-800 truncate w-90 ellipsis
//        trash button 30×30 r-6.67 p-6.67 — single-click delete
interface SubtitleCancelActionBarProps {
  text: string;
  onRemove: () => void;
}

export function SubtitleCancelActionBar({
  text,
  onRemove,
}: SubtitleCancelActionBarProps) {
  return (
    <div
      className="flex items-center gap-5 rounded-[10px] bg-white px-4 py-2 shadow-[2px_2px_20px_0px_rgba(0,0,0,0.25)]"
      data-figma-node="1669:49437"
    >
      <span className="flex items-center gap-[10px]">
        <span className="text-[14px] font-medium leading-[1.4] tracking-[-0.35px] text-grayscale-500">
          선택
        </span>
        <span className="w-[90px] overflow-hidden text-ellipsis whitespace-nowrap text-[14px] font-medium leading-[1.4] tracking-[-0.35px] text-grayscale-800">
          {text || "취소할 내용"}
        </span>
      </span>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onRemove();
        }}
        aria-label="삭제"
        className="flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-[6.67px] p-[6.67px] text-red-h-500 hover:bg-red-h-50"
      >
        <Trash2 className="h-[16.67px] w-[16.67px]" strokeWidth={1.5} />
      </button>
    </div>
  );
}
