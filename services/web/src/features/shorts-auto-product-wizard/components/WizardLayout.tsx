// ============================================================================
// Wizard chrome — header breadcrumb + Next/Prev buttons.
//
// Minimal stepper (no UI lib dependency). Each step page passes its index
// (1-4) and renders its own content as children. The layout owns the
// breadcrumb visualization + the consistent "다음 >" / "< 뒤로" affordances.
// ============================================================================

"use client";

import Link from "next/link";
import type { ReactNode } from "react";

const STEPS = [
  { idx: 1, label: "동영상 선택" },
  { idx: 2, label: "생성 기준 설정" },
  { idx: 3, label: "제품 선택" },
  { idx: 4, label: "쇼츠 자동 생성" },
] as const;

interface Props {
  currentStep: 1 | 2 | 3 | 4;
  /** Visible header instruction text (right side). */
  heading: string;
  /** Optional Next button — pass null to omit (e.g., terminal step). */
  next?: { label: string; onClick: () => void; disabled?: boolean } | null;
  /** Optional Back href. Defaults to ``/export/shorts/auto`` from step 1. */
  backHref?: string;
  children: ReactNode;
}

export function WizardLayout({
  currentStep,
  heading,
  next,
  backHref = "/export/shorts/auto",
  children,
}: Props) {
  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <header className="space-y-3">
        <div className="flex items-center justify-between gap-4">
          <Link
            href={backHref}
            className="text-sm text-gray-600 hover:underline"
          >
            &lt; 뒤로
          </Link>
          <nav className="flex items-center gap-2 text-sm text-gray-700">
            {STEPS.map((step) => (
              <span
                key={step.idx}
                className={
                  step.idx === currentStep
                    ? "font-semibold text-indigo-600"
                    : "text-gray-500"
                }
              >
                {step.idx}.{step.label}
                {step.idx < STEPS.length ? " >" : ""}
              </span>
            ))}
          </nav>
        </div>
        <div className="flex items-center justify-between gap-4">
          <p className="text-sm text-gray-700">{heading}</p>
          {next ? (
            <button
              type="button"
              onClick={next.onClick}
              disabled={next.disabled}
              className="rounded-md bg-indigo-500 px-4 py-1.5 text-sm font-medium text-white transition hover:bg-indigo-600 disabled:bg-gray-300 disabled:text-gray-500"
              data-testid="wizard-next"
            >
              {next.label}
            </button>
          ) : null}
        </div>
      </header>
      <main>{children}</main>
    </div>
  );
}
