// ============================================================================
// 3-step breadcrumb for the inline auto-shorts wizard rendered on the video
// detail page. Visual model per Figma: filled dark circle for the active or
// completed step, light circle for upcoming. Stateless — caller passes
// ``currentStep``.
//
// Distinct from the legacy 4-step ``WizardLayout`` breadcrumb because:
//   * inline flow drops "동영상 선택" (videoId is known from page context)
//   * inline flow stops at "AI 쇼츠 생성" — the result page handles itself
// ============================================================================

"use client";

import { cn } from "@/lib/utils";

const STEPS = [
  { idx: 1 as const, label: "옵션 설정" },
  { idx: 2 as const, label: "상품 선택" },
  { idx: 3 as const, label: "AI 쇼츠 생성" },
] as const;

interface Props {
  currentStep: 1 | 2 | 3;
  className?: string;
}

export function InlineWizardBreadcrumb({ currentStep, className }: Props) {
  return (
    <nav
      className={cn("flex items-center gap-3 text-sm", className)}
      aria-label="쇼츠 생성 진행 단계"
      data-testid="inline-wizard-breadcrumb"
    >
      {STEPS.map((step, i) => {
        const isActive = step.idx === currentStep;
        const isUpcoming = step.idx > currentStep;
        return (
          <div key={step.idx} className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "flex h-6 w-6 items-center justify-center rounded-full text-xs font-medium",
                  isActive
                    ? "bg-gray-900 text-white"
                    : isUpcoming
                      ? "bg-gray-200 text-gray-500"
                      : "bg-gray-300 text-gray-600",
                )}
                data-testid={`inline-wizard-breadcrumb-step-${step.idx}-circle`}
                data-active={isActive}
              >
                {step.idx}
              </span>
              <span
                className={cn(
                  "font-medium",
                  isActive ? "text-gray-900" : "text-gray-400",
                )}
              >
                {step.label}
              </span>
            </div>
            {i < STEPS.length - 1 ? (
              <span className="text-gray-300" aria-hidden="true">
                ›
              </span>
            ) : null}
          </div>
        );
      })}
    </nav>
  );
}
