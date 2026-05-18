// ============================================================================
// Inline-wizard variant of ProductDistributionToggle — two side-by-side
// cards per Figma #12 (top of the criteria step). Same value contract as
// the legacy ``ProductDistributionToggle``: emits "single" or "multi" via
// the existing ``ProductDistribution`` type.
//
// "여러 상품" still hits the same backend gate as the legacy toggle —
// MULTI_PRODUCT_PICKER_ENABLED returns 422 if disabled, surfaced by the
// criteria panel's submit error path.
// ============================================================================

"use client";

import type { ProductDistribution } from "@/lib/types/shorts-auto-product-wizard";

import { cn } from "@/lib/utils";

interface Props {
  value: ProductDistribution;
  onChange: (next: ProductDistribution) => void;
  disabled?: boolean;
}

const OPTIONS: Array<{
  value: ProductDistribution;
  label: string;
  description: string;
}> = [
  {
    value: "single",
    label: "상품별 쇼츠",
    description: "하나의 상품을 중심으로 한 편의 쇼츠 생성",
  },
  {
    value: "multi",
    label: "통합 쇼츠",
    description: "여러 상품을 한 편의 쇼츠에 담아 생성",
  },
];

export function InlineDistributionToggle({
  value,
  onChange,
  disabled,
}: Props) {
  return (
    <div className="space-y-2">
      <label className="block text-sm font-medium text-gray-900">
        생성 유형
      </label>
      <div className="grid grid-cols-2 gap-3">
        {OPTIONS.map((opt) => {
          const isActive = value === opt.value;
          return (
            <button
              key={opt.value}
              type="button"
              onClick={() => onChange(opt.value)}
              disabled={disabled}
              className={cn(
                "rounded-md border px-4 py-4 text-center transition",
                isActive
                  ? "border-gray-900 ring-2 ring-gray-900"
                  : "border-gray-200 hover:border-gray-400",
                disabled && "cursor-not-allowed opacity-50",
              )}
              data-testid={`inline-distribution-${opt.value}`}
              data-active={isActive}
            >
              <span
                className={cn(
                  "block text-sm font-semibold",
                  isActive ? "text-gray-900" : "text-gray-500",
                )}
              >
                {opt.label}
              </span>
              <span className="mt-1 block text-xs text-gray-500">
                {opt.description}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
