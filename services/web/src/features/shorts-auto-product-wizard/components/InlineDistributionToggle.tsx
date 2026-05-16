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

// figma: 1713-288216  (cache: .figma-cache/1713-288216_phase2_wizard-criteria.api.json)
// node-name: Distribution Toggle (생성 유형)  · spec: label=16/600, cards gap=20, card padL/R=20 padT/B=10, radius=10, active border=2 heimdex-navy-500

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
    <div className="space-y-[12px] font-pretendard">
      <label className="block text-[16px] font-semibold text-grayscale-800">
        생성 유형
      </label>
      <div className="grid grid-cols-2 gap-5">
        {OPTIONS.map((opt) => {
          const isActive = value === opt.value;
          return (
            <button
              key={opt.value}
              type="button"
              onClick={() => onChange(opt.value)}
              disabled={disabled}
              className={cn(
                "rounded-[10px] border px-5 py-2.5 text-center transition",
                isActive
                  ? "border-2 border-heimdex-navy-500 bg-white"
                  : "border border-grayscale-100 bg-white hover:border-heimdex-navy-400",
                disabled && "cursor-not-allowed opacity-50",
              )}
              data-testid={`inline-distribution-${opt.value}`}
              data-active={isActive}
            >
              <span
                className={cn(
                  "block text-[16px] font-semibold tracking-[-0.4px]",
                  isActive ? "text-heimdex-navy-500" : "text-grayscale-500",
                )}
              >
                {opt.label}
              </span>
              <span className="mt-[4px] block text-[12px] font-medium text-grayscale-500">
                {opt.description}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
