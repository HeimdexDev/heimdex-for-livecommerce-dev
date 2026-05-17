"use client";

interface Props {
  onClick: () => void;
  disabled?: boolean;
}

// figma: 1669:48308 (GNB Secondary) — h=32 border #7b7b7b px=10 py=6 r=8
// fs=12 SemiBold. Height matches the 내보내기 Primary button so the GNB
// pair lines up. No leading icon — the icon was dropped per the figma.
export function TemplateSaveMenu({ onClick, disabled = false }: Props) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="inline-flex h-8 items-center justify-center rounded-[8px] border border-neutral-h-500 bg-white px-[10px] py-[6px] text-[12px] font-semibold text-neutral-h-500 transition-colors hover:bg-grayscale-10 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-white"
    >
      템플릿 저장
    </button>
  );
}
