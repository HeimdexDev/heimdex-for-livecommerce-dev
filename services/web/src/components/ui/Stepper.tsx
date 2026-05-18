import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

interface Step {
  idx: number;
  label: string;
}

interface Props {
  steps: Step[];
  currentStep: number;
  className?: string;
}

export function Stepper({ steps, currentStep, className }: Props) {
  return (
    <ol
      className={cn(
        "flex items-center gap-[10px] font-pretendard",
        className,
      )}
      aria-label="진행 단계"
    >
      {steps.map((step, i) => {
        const isActive = step.idx === currentStep;
        const isLast = i === steps.length - 1;
        return (
          <li
            key={step.idx}
            className="flex items-center gap-[10px]"
            aria-current={isActive ? "step" : undefined}
          >
            <div className="flex items-center gap-[8px]">
              <span
                className={cn(
                  "flex h-[24px] w-[24px] items-center justify-center rounded-full text-[12px] font-semibold leading-none text-white",
                  isActive ? "bg-heimdex-navy-500" : "bg-neutral-h-300",
                )}
              >
                {step.idx}
              </span>
              <span
                className={cn(
                  "whitespace-nowrap text-[20px] font-semibold leading-none tracking-[-0.5px]",
                  isActive ? "text-black" : "text-neutral-h-300",
                )}
              >
                {step.label}
              </span>
            </div>
            {!isLast ? (
              <ChevronRight
                className="h-[24px] w-[24px] text-neutral-h-300"
                strokeWidth={2}
                aria-hidden="true"
              />
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
