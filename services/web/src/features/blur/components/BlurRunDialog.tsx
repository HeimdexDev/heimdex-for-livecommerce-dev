/**
 * Modal that lets the user pick blur categories before submitting a
 * new blur job. Defaults mirror the backend's BlurOptions:
 * faces + license plates + card objects. Logo blur is opt-in because
 * it would blur the product being sold in livecommerce footage.
 *
 * Closes on Escape or backdrop click. On confirm, calls ``onSubmit``
 * with the selected category list; the parent handles the POST and
 * navigation.
 */
"use client";

import { useCallback, useEffect, useState } from "react";

import type { BlurCategory } from "@/lib/api/blur";

type CategoryChoice = {
  key: BlurCategory;
  label: string;
  hint: string;
  defaultOn: boolean;
};

const CATEGORY_CHOICES: CategoryChoice[] = [
  { key: "face", label: "얼굴", hint: "검출된 얼굴에 블러를 적용합니다.", defaultOn: true },
  { key: "license_plate", label: "번호판", hint: "차량 번호판을 블러 처리합니다.", defaultOn: true },
  { key: "card_object", label: "신용카드", hint: "신용카드, 주민등록증 등을 블러 처리합니다.", defaultOn: true },
  { key: "logo", label: "로고 (주의)", hint: "상품 로고까지 블러 처리됩니다. 라이브커머스 영상에서는 권장하지 않습니다.", defaultOn: false },
];

export interface BlurRunDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (categories: BlurCategory[]) => void | Promise<void>;
  submitting?: boolean;
  submitError?: string | null;
}

export function BlurRunDialog({
  isOpen,
  onClose,
  onSubmit,
  submitting = false,
  submitError = null,
}: BlurRunDialogProps) {
  const [selected, setSelected] = useState<Record<BlurCategory, boolean>>(() => {
    const initial: Record<string, boolean> = {};
    for (const c of CATEGORY_CHOICES) initial[c.key] = c.defaultOn;
    return initial as Record<BlurCategory, boolean>;
  });

  // Reset the form whenever the dialog re-opens.
  useEffect(() => {
    if (isOpen) {
      const initial: Record<string, boolean> = {};
      for (const c of CATEGORY_CHOICES) initial[c.key] = c.defaultOn;
      setSelected(initial as Record<BlurCategory, boolean>);
    }
  }, [isOpen]);

  // Close on Escape.
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !submitting) onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [isOpen, submitting, onClose]);

  const toggle = useCallback((key: BlurCategory) => {
    setSelected((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

  const handleSubmit = useCallback(async () => {
    const categories = CATEGORY_CHOICES
      .map((c) => c.key)
      .filter((k) => selected[k]);
    if (categories.length === 0) return;
    await onSubmit(categories);
  }, [selected, onSubmit]);

  if (!isOpen) return null;

  const anySelected = CATEGORY_CHOICES.some((c) => selected[c.key]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={submitting ? undefined : onClose}
    >
      <div
        className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-gray-900">블러 처리 설정</h2>
        <p className="mt-1 text-sm text-gray-600">
          블러할 항목을 선택해 주세요. 모든 항목은 한 번에 검출되며,
          내보내기 시점에 원하는 항목만 선택하여 ProRes 4444 레이어로 추출할 수 있습니다.
        </p>

        <div className="mt-4 space-y-3">
          {CATEGORY_CHOICES.map((choice) => (
            <label
              key={choice.key}
              className="flex cursor-pointer items-start gap-3 rounded-lg border border-gray-200 p-3 hover:bg-gray-50"
            >
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                checked={selected[choice.key]}
                onChange={() => toggle(choice.key)}
                disabled={submitting}
              />
              <div className="flex-1">
                <div className="text-sm font-medium text-gray-900">{choice.label}</div>
                <div className="mt-0.5 text-xs text-gray-500">{choice.hint}</div>
              </div>
            </label>
          ))}
        </div>

        {submitError && (
          <div className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-800">
            {submitError}
          </div>
        )}

        <div className="mt-6 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            취소
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitting || !anySelected}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {submitting ? "전송 중..." : "블러 처리 시작"}
          </button>
        </div>
      </div>
    </div>
  );
}
