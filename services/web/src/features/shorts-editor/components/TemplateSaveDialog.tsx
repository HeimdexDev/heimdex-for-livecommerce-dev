"use client";

import { useEffect, useState } from "react";

// figma: 1670:186593 — 템플릿 저장 팝업
// spec: bg-white r-20 p-24 gap-28 items-center justify-center shadow-dialog
//       info icon circle 24px heimdex-navy-500 + "i" 12px white
//       title "템플릿으로 저장할까요?" 18px bold neutral-h-800
//       body  "현재 텍스트/배경 스타일을 템플릿으로 저장합니다." 14px medium grayscale-800
//       input r-10 border-grayscale-500 px=10 py=8 w-219 placeholder-neutral-h-300
//       cancel secondary + save primary (disabled when empty) h-36 r-8 px-12 py-8 fs-14
interface Props {
  open: boolean;
  onClose: () => void;
  onSave: (name: string, isShared: boolean) => void | Promise<void>;
}

export function TemplateSaveDialog({ open, onClose, onSave }: Props) {
  const [name, setName] = useState("");

  useEffect(() => {
    if (!open) return;
    setName("");
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;

  const canSubmit = name.trim().length > 0;
  const handleSubmit = () => {
    if (canSubmit) void onSave(name.trim(), false);
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="템플릿 저장"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex flex-col items-center justify-center gap-7 rounded-[20px] bg-white p-6 shadow-[2px_2px_20px_0px_rgba(0,0,0,0.25)]"
      >
        <div className="flex flex-col items-center justify-center gap-3">
          <div
            aria-hidden
            className="flex h-6 w-6 items-center justify-center rounded-full bg-heimdex-navy-500"
          >
            <span className="font-pretendard text-[14px] font-bold leading-none text-white">
              i
            </span>
          </div>
          <p className="text-[18px] font-bold leading-[1.4] tracking-[-0.45px] text-neutral-h-800">
            템플릿으로 저장할까요?
          </p>
          <p className="text-center text-[14px] font-medium leading-[1.4] tracking-[-0.35px] text-grayscale-800">
            현재 텍스트/배경 스타일을 템플릿으로 저장합니다.
          </p>
        </div>

        <div className="flex items-center justify-center gap-[10px]">
          <input
            type="text"
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSubmit();
            }}
            placeholder="템플릿 이름을 적어주세요."
            className="h-9 w-[219px] rounded-[10px] border border-grayscale-500 bg-white px-[10px] py-[8px] text-[14px] font-medium leading-[1.4] tracking-[-0.35px] text-grayscale-800 placeholder:text-neutral-h-300 focus:border-heimdex-navy-500 focus:outline-none focus:ring-1 focus:ring-heimdex-navy-500"
          />
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="inline-flex h-9 items-center justify-center rounded-[8px] border border-neutral-h-500 px-3 py-2 text-[14px] font-semibold text-neutral-h-500 transition-colors hover:bg-grayscale-10"
            >
              취소
            </button>
            <button
              type="button"
              onClick={handleSubmit}
              disabled={!canSubmit}
              className={
                canSubmit
                  ? "inline-flex h-9 items-center justify-center rounded-[8px] bg-heimdex-navy-500 px-3 py-2 text-[14px] font-semibold text-white transition-colors hover:bg-heimdex-navy-600"
                  : "inline-flex h-9 cursor-not-allowed items-center justify-center rounded-[8px] bg-neutral-h-100 px-3 py-2 text-[14px] font-semibold text-neutral-h-300"
              }
            >
              저장
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
