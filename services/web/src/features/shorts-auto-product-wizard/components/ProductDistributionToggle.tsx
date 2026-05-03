// ============================================================================
// 상품 구분 여부 — 개별 상품 / 여러 상품
//
// Per the wizard mockup:
//   * 개별 상품 (single): each generated short is dedicated to one product.
//   * 여러 상품 (multi): each generated short can mix multiple products.
//
// In Phase 4 only ``single`` is implemented end-to-end (the runner +
// SingleProductSubsetPicker round-robin distribution). ``multi`` is the
// Phase 5 deliverable — until ``MULTI_PRODUCT_PICKER_ENABLED=true`` flips
// on the backend, selecting it returns a 422 at submit time, which the
// criteria page surfaces verbatim. We keep the toggle visible so the
// product surface area is complete.
// ============================================================================

"use client";

import type { ProductDistribution } from "@/lib/types/shorts-auto-product-wizard";

interface Props {
  value: ProductDistribution;
  onChange: (next: ProductDistribution) => void;
}

const OPTIONS: Array<{
  value: ProductDistribution;
  label: string;
  description: string;
}> = [
  {
    value: "single",
    label: "개별 상품",
    description: "각 제품별로 구분해서 쇼츠를 제작해요",
  },
  {
    value: "multi",
    label: "여러 상품",
    description: "여러 상품을 하나의 쇼츠에 보여줘도 돼요",
  },
];

export function ProductDistributionToggle({ value, onChange }: Props) {
  return (
    <div className="space-y-2">
      <label className="block text-sm font-medium text-gray-700">
        상품 구분 여부
      </label>
      <div className="space-y-2">
        {OPTIONS.map((opt) => (
          <label
            key={opt.value}
            className={`flex cursor-pointer items-start gap-3 rounded-md border p-3 transition ${
              value === opt.value
                ? "border-indigo-500 bg-indigo-50"
                : "border-gray-300 bg-white hover:bg-gray-50"
            }`}
            data-testid={`distribution-${opt.value}`}
          >
            <input
              type="radio"
              name="product-distribution"
              checked={value === opt.value}
              onChange={() => onChange(opt.value)}
              className="mt-0.5"
            />
            <span>
              <span className="block text-sm font-medium text-gray-800">
                {opt.label}
              </span>
              <span className="block text-xs text-gray-500">
                {opt.description}
              </span>
            </span>
          </label>
        ))}
      </div>
    </div>
  );
}
