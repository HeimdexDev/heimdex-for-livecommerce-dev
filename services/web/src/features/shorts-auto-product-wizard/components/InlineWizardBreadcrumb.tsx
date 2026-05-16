// ============================================================================
// figma: 1713:288141 (Frame 1707484839 — wizard GNB step indicator overlay)
//
// Step breadcrumb for the inline auto-shorts wizard. Two visual variants:
//
//   * ``three-step`` (default) — used by criteria + product steps:
//       1 옵션 설정 › 2 상품 선택 › 3 AI 쇼츠 생성
//   * ``two-step`` — used by the loading screen + edit-clips chrome:
//       1 옵션 설정 › 2 AI 쇼츠 생성
//     The two-step variant collapses criteria + product into the single
//     "옵션 설정" anchor since by the time the user sees it both choices
//     are locked in. The label "AI 쇼츠 생성" is preserved across variants.
//
// Stateless — caller passes ``currentStep`` (narrowed by variant) and the
// component renders the breadcrumb. Distinct from the legacy 4-step
// ``WizardLayout`` breadcrumb (deleted in Phase D3 of the inline-wizard plan).
// ============================================================================

"use client";

import { ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";

const STEPS_THREE = [
  { idx: 1 as const, label: "옵션 설정" },
  { idx: 2 as const, label: "상품 선택" },
  { idx: 3 as const, label: "AI 쇼츠 생성" },
] as const;

const STEPS_TWO = [
  { idx: 1 as const, label: "옵션 설정" },
  { idx: 2 as const, label: "AI 쇼츠 생성" },
] as const;

// Discriminated union keeps strict-mode type safety — callers passing a
// raw ``currentStep`` literal get the right narrow type for their variant.
type Props =
  | {
      variant?: "three-step";
      currentStep: 1 | 2 | 3;
      className?: string;
    }
  | {
      variant: "two-step";
      currentStep: 1 | 2;
      className?: string;
    };

export function InlineWizardBreadcrumb(props: Props) {
  const variant = props.variant ?? "three-step";
  const steps = variant === "two-step" ? STEPS_TWO : STEPS_THREE;

  return (
    <nav
      className={cn(
        "flex items-center gap-[10px] font-pretendard",
        props.className,
      )}
      aria-label="쇼츠 생성 진행 단계"
      data-testid="inline-wizard-breadcrumb"
      data-variant={variant}
    >
      {steps.map((step, i) => {
        const isActive = step.idx === props.currentStep;
        return (
          <div key={step.idx} className="flex items-center gap-[10px]">
            <div className="flex items-center gap-[8px]">
              <span
                className={cn(
                  "flex h-[24px] w-[24px] items-center justify-center rounded-full text-[12px] font-semibold leading-none text-white",
                  isActive ? "bg-heimdex-navy-500" : "bg-neutral-h-300",
                )}
                data-testid={`inline-wizard-breadcrumb-step-${step.idx}-circle`}
                data-active={isActive}
              >
                {step.idx}
              </span>
              <span
                className={cn(
                  "whitespace-nowrap text-[20px] font-semibold leading-none",
                  isActive ? "text-black" : "text-neutral-h-300",
                )}
              >
                {step.label}
              </span>
            </div>
            {i < steps.length - 1 ? (
              <ChevronRight
                className="h-[24px] w-[24px] text-neutral-h-300"
                strokeWidth={2}
                aria-hidden="true"
              />
            ) : null}
          </div>
        );
      })}
    </nav>
  );
}
