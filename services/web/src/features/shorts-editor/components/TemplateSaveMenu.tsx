"use client";

import { Save } from "lucide-react";

interface Props {
  onClick: () => void;
  disabled?: boolean;
}

// figma: 1713:274774 (템플릿 패널 진입 버튼)
// EditorHeader 의 "현재 스타일을 템플릿으로 저장" 트리거.
export function TemplateSaveMenu({ onClick, disabled = false }: Props) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium text-grayscale-700 transition-colors hover:bg-grayscale-10 hover:text-heimdex-navy-500 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-transparent disabled:hover:text-grayscale-700"
    >
      <Save className="h-4 w-4" strokeWidth={2} />
      템플릿 저장
    </button>
  );
}
